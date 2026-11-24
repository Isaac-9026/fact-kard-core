"""Configuración → Períodos e IGV → «Abrir año»."""
import threading
from datetime import date
from decimal import Decimal
from unittest import mock

from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.auditoria.models import Auditoria
from apps.catalogos.models import Moneda
from apps.empresas.apertura_anio import abrir_anio, vista_previa_anio
from apps.empresas.models import ConfigIgvPeriodo, Empresa, Periodo, TasaIgvVigencia
from apps.usuarios.models import Usuario, UsuarioEmpresa


class AbrirAnioTests(TestCase):
    def setUp(self):
        moneda = Moneda.objects.create(codigo='PEN', nombre='Soles')
        self.empresa = Empresa.objects.create(ruc='20100070971', razon_social='EMPRESA A S.A.C.', moneda_base_codigo=moneda)
        self.otra = Empresa.objects.create(ruc='20100070972', razon_social='EMPRESA B S.A.C.', moneda_base_codigo=moneda)
        self.admin = Usuario.objects.create(username='admin_a', email='a@test.pe', password_hash='hash')
        self.usuario = Usuario.objects.create(username='user_a', email='u@test.pe', password_hash='hash')
        UsuarioEmpresa.objects.create(usuario=self.admin, empresa=self.empresa, rol='ADMIN')
        UsuarioEmpresa.objects.create(usuario=self.usuario, empresa=self.empresa, rol='USUARIO')
        UsuarioEmpresa.objects.create(usuario=self.admin, empresa=self.otra, rol='ADMIN')
        TasaIgvVigencia.objects.create(empresa=self.empresa, vigente_desde=date(2011, 3, 1), tasa_pct=Decimal('18'))
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self.url = reverse('periodo-abrir-anio')
        self.headers = {'HTTP_X_EMPRESA_ID': str(self.empresa.id)}

    def enero_cerrado(self):
        enero = Periodo.objects.create(
            empresa=self.empresa, anio=2023, mes=1, orden=202301, fecha_inicio=date(2023, 1, 1),
            fecha_fin=date(2023, 1, 31), estado='CERRADO',
        )
        ConfigIgvPeriodo.objects.create(empresa=self.empresa, periodo=enero, metodo='PRORRATA',
                                        porcentaje_recuperable=Decimal('62.5000'))
        return enero

    def abrir(self, anio, meses):
        return self.client.post(self.url, {'anio': anio, 'meses': meses}, format='json', **self.headers)

    def test_crea_los_11_que_faltan_y_conserva_enero_cerrado(self):
        enero = self.enero_cerrado()
        previa = self.client.get(self.url, {'anio': 2023}, **self.headers)
        self.assertEqual(previa.status_code, 200)
        self.assertEqual(previa.data['faltantes'], list(range(2, 13)))
        self.assertEqual((previa.data['meses'][0]['existe'], previa.data['meses'][0]['estado']), (True, 'CERRADO'))
        self.assertIsNone(previa.data['advertencia_igv'])

        r = self.abrir(2023, list(range(1, 13)))
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data['total_creados'], r.data['total_existentes']), (11, 1))
        periodos = Periodo.objects.filter(empresa=self.empresa, anio=2023).order_by('mes')
        self.assertEqual(periodos.count(), 12)
        self.assertTrue(all(p.estado == 'ABIERTO' for p in periodos if p.mes > 1))
        enero.refresh_from_db()
        self.assertEqual(enero.estado, 'CERRADO')
        self.assertEqual(ConfigIgvPeriodo.objects.get(periodo=enero).metodo, 'PRORRATA')
        marzo = periodos.get(mes=3)
        self.assertEqual((marzo.orden, marzo.fecha_inicio, marzo.fecha_fin), (202303, date(2023, 3, 1), date(2023, 3, 31)))

        # Cada mes creado queda en Auditoría, solo en la empresa activa.
        auditados = Auditoria.objects.filter(empresa_id=self.empresa.id, entidad='periodo', accion='CREAR')
        self.assertEqual(set(auditados.values_list('registro_id', flat=True)), {p.id for p in periodos if p.mes > 1})
        self.assertFalse(Periodo.objects.filter(empresa=self.otra).exists())
        self.assertFalse(Auditoria.objects.filter(empresa_id=self.otra.id).exists())

        repetido = self.abrir(2023, list(range(1, 13)))
        self.assertEqual(repetido.status_code, 200)
        self.assertEqual((repetido.data['total_creados'], repetido.data['total_existentes']), (0, 12))
        self.assertEqual(Periodo.objects.filter(empresa=self.empresa, anio=2023).count(), 12)

    def test_solo_julio_a_diciembre(self):
        self.enero_cerrado()
        r = self.abrir(2023, [7, 8, 9, 10, 11, 12])
        self.assertEqual((r.data['total_creados'], r.data['total_existentes']), (6, 1))
        self.assertEqual(sorted(Periodo.objects.filter(empresa=self.empresa).values_list('mes', flat=True)), [1, 7, 8, 9, 10, 11, 12])
        # Como en la pantalla: se envían solo los que faltan y se informa cuántos ya existían en el año.
        r = self.abrir(2023, [2, 3])
        self.assertEqual((r.data['total_creados'], r.data['total_existentes']), (2, 7))

    def test_febrero_bisiesto(self):
        self.abrir(2024, [2])
        self.assertEqual(Periodo.objects.get(empresa=self.empresa, anio=2024, mes=2).fecha_fin, date(2024, 2, 29))
        self.abrir(2023, [2])
        self.assertEqual(Periodo.objects.get(empresa=self.empresa, anio=2023, mes=2).fecha_fin, date(2023, 2, 28))

    def test_validaciones_del_servidor(self):
        with mock.patch('apps.empresas.apertura_anio.timezone.localdate', return_value=date(2026, 11, 24)):
            for anio in (1999, 2028, 'abc', None):
                with self.subTest(anio=anio):
                    self.assertEqual(self.abrir(anio, [1]).status_code, 400)
                    self.assertEqual(self.client.get(self.url, {'anio': anio or ''}, **self.headers).status_code, 400)
            self.assertEqual(self.abrir(2027, [1]).status_code, 201)       # año actual + 1 sí
            self.assertEqual(self.abrir(2000, [1]).status_code, 201)
        for meses in ([], [0], [13], ['3.5'], 'enero', None, [True]):
            with self.subTest(meses=meses):
                self.assertEqual(self.abrir(2023, meses).status_code, 400)
        self.assertFalse(Periodo.objects.filter(empresa=self.empresa, anio=2023).exists())

    def test_permisos_y_empresa_activa(self):
        self.client.force_authenticate(user=self.usuario)
        self.assertEqual(self.abrir(2023, [1]).status_code, 403)
        self.assertEqual(self.client.get(self.url, {'anio': 2023}, **self.headers).status_code, 403)
        sin_acceso = Empresa.objects.create(ruc='20100070973', razon_social='C', moneda_base_codigo=self.empresa.moneda_base_codigo)
        self.client.force_authenticate(user=self.admin)
        r = self.client.post(self.url, {'anio': 2023, 'meses': [1]}, format='json', HTTP_X_EMPRESA_ID=str(sin_acceso.id))
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Periodo.objects.exists())

    def test_advertencia_de_igv_incompleto_permite_continuar(self):
        TasaIgvVigencia.objects.filter(empresa=self.empresa).delete()
        TasaIgvVigencia.objects.create(empresa=self.empresa, vigente_desde=date(2023, 3, 15), tasa_pct=Decimal('18'))
        previa = vista_previa_anio(empresa_id=self.empresa.id, anio=2023)
        igv = {m['mes']: m['igv'] for m in previa['meses']}
        self.assertEqual((igv[1]['cubierto'], igv[1]['dias_sin_cobertura']), (False, 31))
        self.assertEqual((igv[3]['cubierto'], igv[3]['dias_sin_cobertura'], igv[3]['sin_cobertura_hasta']), (False, 14, '2023-03-14'))
        self.assertTrue(igv[4]['cubierto'])
        self.assertIn('2023-01, 2023-02, 2023-03', previa['advertencia_igv'])
        r = abrir_anio(empresa_id=self.empresa.id, usuario=self.admin, anio=2023, meses=[2, 3, 4])
        self.assertEqual(r['total_creados'], 3)
        self.assertIn('2023-02, 2023-03', r['advertencia_igv'])
        self.assertNotIn('2023-04', r['advertencia_igv'])

    def test_sin_vigencias_avisa_todos_los_meses(self):
        TasaIgvVigencia.objects.filter(empresa=self.empresa).delete()
        previa = vista_previa_anio(empresa_id=self.empresa.id, anio=2023)
        self.assertTrue(all(not m['igv']['cubierto'] for m in previa['meses']))
        self.assertIn('no tiene vigencias', previa['advertencia_igv'])

    def test_falla_a_mitad_no_deja_nada(self):
        from apps.empresas import apertura_anio
        original = apertura_anio.registrar_auditoria
        llamadas = []

        def falla_en_la_tercera(**kwargs):
            llamadas.append(1)
            if len(llamadas) == 3:
                raise RuntimeError('falla simulada')
            return original(**kwargs)

        with mock.patch('apps.empresas.apertura_anio.registrar_auditoria', side_effect=falla_en_la_tercera):
            with self.assertRaises(RuntimeError):
                abrir_anio(empresa_id=self.empresa.id, usuario=self.admin, anio=2023, meses=[1, 2, 3, 4])
        self.assertFalse(Periodo.objects.filter(empresa=self.empresa, anio=2023).exists())

    def test_nuevo_periodo_sigue_igual_con_su_auditoria(self):
        r = self.client.post(reverse('periodo-list-create'), {
            'anio': 2026, 'mes': 4, 'fecha_inicio': '2026-04-01', 'fecha_fin': '2026-04-30',
        }, format='json', **self.headers)
        self.assertEqual(r.status_code, 201)
        self.assertEqual((r.data['orden'], r.data['estado']), (202604, 'ABIERTO'))
        self.assertTrue(Auditoria.objects.filter(entidad='periodo', registro_id=r.data['id'], accion='CREAR').exists())
        with self.assertRaises(ValidationError):
            abrir_anio(empresa_id=self.empresa.id, usuario=self.admin, anio=2026, meses=[])


class AbrirAnioConcurrenteTests(TransactionTestCase):
    def test_dos_solicitudes_simultaneas_no_duplican(self):
        moneda = Moneda.objects.create(codigo='PEN', nombre='Soles')
        empresa = Empresa.objects.create(ruc='20100070974', razon_social='D', moneda_base_codigo=moneda)
        admin = Usuario.objects.create(username='admin_d', email='d@test.pe', password_hash='hash')
        resultados, errores = [], []
        barrera = threading.Barrier(2)

        def abrir():
            try:
                barrera.wait()
                resultados.append(abrir_anio(empresa_id=empresa.id, usuario=admin, anio=2023, meses=list(range(1, 13))))
            except Exception as exc:  # pragma: no cover - se informa abajo
                errores.append(exc)
            finally:
                connection.close()

        hilos = [threading.Thread(target=abrir) for _ in range(2)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        self.assertEqual(errores, [])
        self.assertEqual(sorted(r['total_creados'] for r in resultados), [0, 12])
        self.assertEqual(Periodo.objects.filter(empresa=empresa, anio=2023).count(), 12)
