from decimal import Decimal
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from apps.catalogos.models import Moneda
from apps.empresas.models import Empresa, Establecimiento, ConfigEmpresa, Periodo, ConfigIgvPeriodo
from apps.usuarios.models import Usuario, UsuarioEmpresa
from apps.empresas.services import calcular_hash_cierre, cerrar_periodo, reabrir_periodo
from apps.empresas.models import CierrePeriodo
from apps.kardex.models import Incidencia
from rest_framework.exceptions import ValidationError


class EmpresasModelTest(TestCase):
    def setUp(self):
        self.moneda = Moneda.objects.create(codigo='PEN', nombre='Soles')
        self.empresa = Empresa.objects.create(
            ruc='20100070970',
            razon_social='EMPRESA MODELO S.A.C.',
            moneda_base_codigo=self.moneda
        )

    def test_crear_empresa_y_establecimiento(self):
        est = Establecimiento.objects.create(
            empresa=self.empresa,
            codigo_sunat='0000',
            nombre='PRINCIPAL'
        )
        config = ConfigEmpresa.objects.create(
            empresa=self.empresa,
            tolerancia_residuo_pen=Decimal('0.05'),
            decimales_calculo=6,
            establecimiento_principal=est
        )
        self.assertEqual(config.tolerancia_residuo_pen, Decimal('0.05'))
        self.assertEqual(config.decimales_calculo, 6)
        self.assertEqual(config.regla_redondeo, 'ROUND_HALF_UP')
        self.assertEqual(config.metodo_valuacion, 'CPP')

    def test_empresa_estado_check_constraint(self):
        with self.assertRaises(IntegrityError):
            Empresa.objects.create(
                ruc='20100070971',
                razon_social='TEST INVALID ESTADO',
                moneda_base_codigo=self.moneda,
                estado='ESTADO_INVALIDO'
            )

    def test_config_decimales_calculo_check_constraint(self):
        with self.assertRaises(IntegrityError):
            ConfigEmpresa.objects.create(
                empresa=self.empresa,
                decimales_calculo=10  # Solo entre 2 y 8
            )


class EmpresasApiTest(TestCase):
    def setUp(self):
        self.moneda = Moneda.objects.create(codigo='PEN', nombre='Soles')
        self.usuario = Usuario.objects.create(
            username='dev_b',
            email='devb@factkard.pe',
            password_hash='hash',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.usuario)

    def crear_empresa(self, ruc, razon_social):
        return Empresa.objects.create(
            ruc=ruc,
            razon_social=razon_social,
            moneda_base_codigo=self.moneda,
        )

    def test_api_crear_empresa_crea_config_y_asignacion_admin(self):
        response = self.client.post(
            reverse('empresa-list-create'),
            {
                'ruc': '20601234567',
                'razon_social': 'NUEVA EMPRESA S.A.C.',
                'nombre_comercial': 'Nueva Empresa',
                'direccion': 'Lima',
                'moneda_base_codigo': 'PEN',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        empresa = Empresa.objects.get(pk=response.data['id'])
        config = ConfigEmpresa.objects.get(empresa=empresa)
        self.assertEqual(config.tolerancia_residuo_pen, Decimal('0.05000000'))
        self.assertEqual(config.decimales_calculo, 6)
        self.assertEqual(config.regla_redondeo, 'ROUND_HALF_UP')
        self.assertEqual(config.metodo_valuacion, 'CPP')
        self.assertTrue(UsuarioEmpresa.objects.filter(
            usuario=self.usuario,
            empresa=empresa,
            rol='ADMIN',
            activo=True,
        ).exists())

    def test_establecimientos_aislados_por_empresa_activa(self):
        empresa_a = self.crear_empresa('20600000001', 'EMPRESA A')
        empresa_b = self.crear_empresa('20600000002', 'EMPRESA B')
        UsuarioEmpresa.objects.create(usuario=self.usuario, empresa=empresa_b, rol='USUARIO')
        establecimiento_a = Establecimiento.objects.create(
            empresa=empresa_a,
            codigo_sunat='A001',
            nombre='LOCAL A',
        )
        establecimiento_b = Establecimiento.objects.create(
            empresa=empresa_b,
            codigo_sunat='B001',
            nombre='LOCAL B',
        )

        response = self.client.get(
            reverse('establecimiento-list-create'),
            HTTP_X_EMPRESA_ID=str(empresa_b.id),
        )

        self.assertEqual(response.status_code, 200)
        ids = {item['id'] for item in response.data}
        self.assertIn(establecimiento_b.id, ids)
        self.assertNotIn(establecimiento_a.id, ids)

    def test_patch_establecimiento_ajeno_responde_404(self):
        empresa_a = self.crear_empresa('20600000003', 'EMPRESA A')
        empresa_b = self.crear_empresa('20600000004', 'EMPRESA B')
        UsuarioEmpresa.objects.create(usuario=self.usuario, empresa=empresa_b, rol='ADMIN')
        establecimiento_a = Establecimiento.objects.create(
            empresa=empresa_a,
            codigo_sunat='A002',
            nombre='LOCAL AJENO',
        )

        response = self.client.patch(
            reverse('establecimiento-detail', args=[establecimiento_a.id]),
            {'nombre': 'INTENTO'},
            format='json',
            HTTP_X_EMPRESA_ID=str(empresa_b.id),
        )

        self.assertEqual(response.status_code, 404)
        establecimiento_a.refresh_from_db()
        self.assertEqual(establecimiento_a.nombre, 'LOCAL AJENO')

    def test_config_rechaza_establecimiento_de_otra_empresa(self):
        empresa_a = self.crear_empresa('20600000005', 'EMPRESA A')
        empresa_b = self.crear_empresa('20600000006', 'EMPRESA B')
        ConfigEmpresa.objects.create(empresa=empresa_b)
        UsuarioEmpresa.objects.create(usuario=self.usuario, empresa=empresa_b, rol='ADMIN')
        establecimiento_a = Establecimiento.objects.create(
            empresa=empresa_a,
            codigo_sunat='A003',
            nombre='LOCAL AJENO',
        )

        response = self.client.patch(
            reverse('empresa-config'),
            {'establecimiento_principal': establecimiento_a.id},
            format='json',
            HTTP_X_EMPRESA_ID=str(empresa_b.id),
        )

        self.assertEqual(response.status_code, 400)


class PeriodoModelTest(TestCase):
    def setUp(self):
        from datetime import date
        self.moneda = Moneda.objects.create(codigo='PEN', nombre='Soles')
        self.empresa = Empresa.objects.create(
            ruc='20100070970',
            razon_social='EMPRESA MODELO S.A.C.',
            moneda_base_codigo=self.moneda
        )

    def test_crear_periodo_y_unique_constraint(self):
        from datetime import date
        p = Periodo.objects.create(
            empresa=self.empresa,
            anio=2026,
            mes=1,
            orden=202601,
            fecha_inicio=date(2026, 1, 1),
            fecha_fin=date(2026, 1, 31),
            estado='ABIERTO'
        )
        self.assertEqual(p.estado, 'ABIERTO')

        # Duplicado en empresa, año y mes debe fallar
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Periodo.objects.create(
                    empresa=self.empresa,
                    anio=2026,
                    mes=1,
                    orden=202601,
                    fecha_inicio=date(2026, 1, 1),
                    fecha_fin=date(2026, 1, 31)
                )

    def test_periodo_mes_invalido_check_constraint(self):
        from datetime import date
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Periodo.objects.create(
                    empresa=self.empresa,
                    anio=2026,
                    mes=13,  # Mes inválido
                    orden=202613,
                    fecha_inicio=date(2026, 1, 1),
                    fecha_fin=date(2026, 1, 31)
                )

    def test_periodo_fechas_incoherentes_check_constraint(self):
        from datetime import date
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Periodo.objects.create(
                    empresa=self.empresa,
                    anio=2026,
                    mes=2,
                    orden=202602,
                    fecha_inicio=date(2026, 2, 28),
                    fecha_fin=date(2026, 2, 1)  # fecha_fin < fecha_inicio
                )

    def test_config_igv_periodo_constraints(self):
        from datetime import date
        p = Periodo.objects.create(
            empresa=self.empresa,
            anio=2026,
            mes=3,
            orden=202603,
            fecha_inicio=date(2026, 3, 1),
            fecha_fin=date(2026, 3, 31)
        )
        cfg = ConfigIgvPeriodo.objects.create(
            empresa=self.empresa,
            periodo=p,
            metodo='TOTAL',
            porcentaje_recuperable=Decimal('100.0000')
        )
        self.assertEqual(cfg.metodo, 'TOTAL')

        # Método inválido
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                ConfigIgvPeriodo.objects.create(
                    empresa=self.empresa,
                    periodo=p,
                    metodo='METODO_INVALIDO',
                    porcentaje_recuperable=Decimal('50.0000')
                )


class PeriodosYConfigIgvApiTest(TestCase):
    def setUp(self):
        from datetime import date
        from apps.auditoria.models import Auditoria
        self.moneda = Moneda.objects.create(codigo='PEN', nombre='Soles')

        self.empresa_a = Empresa.objects.create(
            ruc='20100070971',
            razon_social='EMPRESA A S.A.C.',
            moneda_base_codigo=self.moneda,
        )
        self.empresa_b = Empresa.objects.create(
            ruc='20100070972',
            razon_social='EMPRESA B S.A.C.',
            moneda_base_codigo=self.moneda,
        )

        self.admin_user = Usuario.objects.create(
            username='admin_a',
            email='admin_a@test.pe',
            password_hash='hash',
        )
        self.normal_user = Usuario.objects.create(
            username='user_a',
            email='user_a@test.pe',
            password_hash='hash',
        )

        UsuarioEmpresa.objects.create(usuario=self.admin_user, empresa=self.empresa_a, rol='ADMIN')
        UsuarioEmpresa.objects.create(usuario=self.normal_user, empresa=self.empresa_a, rol='USUARIO')

        self.client = APIClient()

    def test_crear_periodo_calcula_orden_y_valida_fechas(self):
        self.client.force_authenticate(user=self.admin_user)
        # Fecha fin menor que fecha inicio debe fallar (400)
        res_bad = self.client.post(
            reverse('periodo-list-create'),
            {
                'anio': 2026,
                'mes': 4,
                'fecha_inicio': '2026-04-30',
                'fecha_fin': '2026-04-01',
            },
            format='json',
            HTTP_X_EMPRESA_ID=str(self.empresa_a.id),
        )
        self.assertEqual(res_bad.status_code, 400)
        self.assertIn('fecha_fin', res_bad.data)

        # Creación válida
        res_ok = self.client.post(
            reverse('periodo-list-create'),
            {
                'anio': 2026,
                'mes': 4,
                'fecha_inicio': '2026-04-01',
                'fecha_fin': '2026-04-30',
            },
            format='json',
            HTTP_X_EMPRESA_ID=str(self.empresa_a.id),
        )
        self.assertEqual(res_ok.status_code, 201)
        self.assertEqual(res_ok.data['orden'], 202604)
        self.assertEqual(res_ok.data['estado'], 'ABIERTO')

    def test_aislamiento_multiempresa_periodos(self):
        from datetime import date
        from apps.empresas.models import Periodo
        # Período en empresa A
        p_a = Periodo.objects.create(
            empresa=self.empresa_a,
            anio=2026,
            mes=1,
            orden=202601,
            fecha_inicio=date(2026, 1, 1),
            fecha_fin=date(2026, 1, 31),
        )
        # Período en empresa B
        p_b = Periodo.objects.create(
            empresa=self.empresa_b,
            anio=2026,
            mes=1,
            orden=202601,
            fecha_inicio=date(2026, 1, 1),
            fecha_fin=date(2026, 1, 31),
        )

        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(
            reverse('periodo-list-create'),
            HTTP_X_EMPRESA_ID=str(self.empresa_a.id),
        )
        self.assertEqual(response.status_code, 200)
        ids = [item['id'] for item in response.data]
        self.assertIn(p_a.id, ids)
        self.assertNotIn(p_b.id, ids)

    def test_config_igv_total_nulo_y_prorrata(self):
        from datetime import date
        from apps.auditoria.models import Auditoria
        self.client.force_authenticate(user=self.admin_user)
        periodo = Periodo.objects.create(
            empresa=self.empresa_a,
            anio=2026,
            mes=5,
            orden=202605,
            fecha_inicio=date(2026, 5, 1),
            fecha_fin=date(2026, 5, 31),
        )

        # 1. Configurar TOTAL -> porcentaje_recuperable debe ser 100.0000
        res_total = self.client.post(
            reverse('periodo-config-igv', args=[periodo.id]),
            {'metodo': 'TOTAL'},
            format='json',
            HTTP_X_EMPRESA_ID=str(self.empresa_a.id),
        )
        self.assertEqual(res_total.status_code, 201)
        self.assertEqual(Decimal(res_total.data['porcentaje_recuperable']), Decimal('100.0000'))

        # Comprobar auditoría
        audit_entry = Auditoria.objects.filter(
            empresa_id=self.empresa_a.id,
            entidad='config_igv_periodo',
            registro_id=res_total.data['id']
        ).first()
        self.assertIsNotNone(audit_entry)
        self.assertEqual(audit_entry.accion, 'CREAR')

        # 2. Modificar a NULO -> porcentaje_recuperable debe ser 0.0000
        res_nulo = self.client.patch(
            reverse('periodo-config-igv', args=[periodo.id]),
            {'metodo': 'NULO'},
            format='json',
            HTTP_X_EMPRESA_ID=str(self.empresa_a.id),
        )
        self.assertEqual(res_nulo.status_code, 200)
        self.assertEqual(Decimal(res_nulo.data['porcentaje_recuperable']), Decimal('0.0000'))

        # 3. Modificar a PRORRATA con valor específico
        res_prorrata = self.client.patch(
            reverse('periodo-config-igv', args=[periodo.id]),
            {'metodo': 'PRORRATA', 'porcentaje_recuperable': '75.5000'},
            format='json',
            HTTP_X_EMPRESA_ID=str(self.empresa_a.id),
        )
        self.assertEqual(res_prorrata.status_code, 200)
        self.assertEqual(Decimal(res_prorrata.data['porcentaje_recuperable']), Decimal('75.5000'))

        # 4. PRORRATA con valor fuera de rango debe fallar
        res_invalido = self.client.patch(
            reverse('periodo-config-igv', args=[periodo.id]),
            {'metodo': 'PRORRATA', 'porcentaje_recuperable': '120.0000'},
            format='json',
            HTTP_X_EMPRESA_ID=str(self.empresa_a.id),
        )
        self.assertEqual(res_invalido.status_code, 400)

    def test_reapertura_periodo_marca_posteriores_cerrados_como_desactualizado(self):
        from datetime import date
        from apps.auditoria.models import Auditoria
        # Crear 3 períodos cerrados
        p1 = Periodo.objects.create(
            empresa=self.empresa_a, anio=2026, mes=1, orden=202601,
            fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 1, 31),
            estado='CERRADO'
        )
        p2 = Periodo.objects.create(
            empresa=self.empresa_a, anio=2026, mes=2, orden=202602,
            fecha_inicio=date(2026, 2, 1), fecha_fin=date(2026, 2, 28),
            estado='CERRADO'
        )
        p3 = Periodo.objects.create(
            empresa=self.empresa_a, anio=2026, mes=3, orden=202603,
            fecha_inicio=date(2026, 3, 1), fecha_fin=date(2026, 3, 31),
            estado='CERRADO'
        )

        # Usuario normal no puede reabrir
        self.client.force_authenticate(user=self.normal_user)
        res_forbidden = self.client.post(
            reverse('periodo-reabrir', args=[p1.id]),
            {'motivo_reapertura': 'Intento no autorizado'},
            format='json',
            HTTP_X_EMPRESA_ID=str(self.empresa_a.id),
        )
        self.assertEqual(res_forbidden.status_code, 403)

        # Admin reabre período 1
        self.client.force_authenticate(user=self.admin_user)
        motivo = 'Factura de compra recibida fuera de plazo'
        res_ok = self.client.post(
            reverse('periodo-reabrir', args=[p1.id]),
            {'motivo_reapertura': motivo},
            format='json',
            HTTP_X_EMPRESA_ID=str(self.empresa_a.id),
        )
        self.assertEqual(res_ok.status_code, 200)
        self.assertEqual(res_ok.data['periodos_desactualizados'], 2)

        # Comprobar estado en base de datos
        p1.refresh_from_db()
        p2.refresh_from_db()
        p3.refresh_from_db()

        self.assertEqual(p1.estado, 'ABIERTO')
        self.assertEqual(p1.motivo_reapertura, motivo)
        self.assertEqual(p1.reabierto_por, self.admin_user)

        self.assertEqual(p2.estado, 'DESACTUALIZADO')
        self.assertIn(motivo, p2.motivo_desactualizado)

        self.assertEqual(p3.estado, 'DESACTUALIZADO')
        self.assertIn(motivo, p3.motivo_desactualizado)

        # Comprobar auditorías registradas
        reabrir_audits = Auditoria.objects.filter(
            empresa_id=self.empresa_a.id,
            entidad='periodo',
            accion='REABRIR',
            registro_id=p1.id
        )
        self.assertTrue(reabrir_audits.exists())

        desactualizar_audits = Auditoria.objects.filter(
            empresa_id=self.empresa_a.id,
            entidad='periodo',
            accion='DESACTUALIZAR'
        )
        self.assertEqual(desactualizar_audits.count(), 2)


class CierrePeriodoModelTest(TestCase):
    def setUp(self):
        import datetime
        from apps.catalogos.models import TipoExistencia, UnidadMedida
        from apps.inventario.models import Producto
        from apps.empresas.models import CierrePeriodo, CierrePeriodoDetalle

        self.moneda = Moneda.objects.create(codigo='PEN', nombre='Soles')
        self.empresa = Empresa.objects.create(
            ruc='20100070970',
            razon_social='EMPRESA MODELO S.A.C.',
            moneda_base_codigo=self.moneda
        )
        self.establecimiento = Establecimiento.objects.create(
            empresa=self.empresa,
            codigo_sunat='0000',
            nombre='PRINCIPAL'
        )
        self.usuario = Usuario.objects.create(
            username='admin_cierre',
            email='cierre@factkard.pe',
            password_hash='hash'
        )
        self.periodo = Periodo.objects.create(
            empresa=self.empresa,
            anio=2026,
            mes=1,
            orden=202601,
            fecha_inicio=datetime.date(2026, 1, 1),
            fecha_fin=datetime.date(2026, 1, 31),
            estado='CERRADO'
        )
        self.tipo_existencia = TipoExistencia.objects.create(codigo='01', descripcion='Mercaderías')
        self.und = UnidadMedida.objects.create(codigo='NIU', descripcion='Unidades')
        self.producto = Producto.objects.create(
            empresa=self.empresa,
            codigo_interno='P001',
            descripcion='Producto Cierre',
            tipo_existencia_codigo=self.tipo_existencia
        )

    def test_creacion_cierre_y_detalle_exitoso(self):
        from apps.empresas.models import CierrePeriodo, CierrePeriodoDetalle

        cierre = CierrePeriodo.objects.create(
            periodo=self.periodo,
            version_calculo=1,
            cerrado_por=self.usuario,
            archivo_excel='/media/cierres/2026_01_v1.xlsx',
            hash_resultado='a1b2c3d4e5f67890abcdef1234567890',
            snapshot_resumen={'total_items': 1, 'valor_total': '1500.00'}
        )
        self.assertIsNotNone(cierre.id)
        self.assertTrue(cierre.vigente)
        self.assertEqual(cierre.periodo.cierres.count(), 1)

        detalle = CierrePeriodoDetalle.objects.create(
            cierre_periodo=cierre,
            producto=self.producto,
            establecimiento=self.establecimiento,
            saldo_cantidad=Decimal('100.00000000'),
            saldo_valor_pen=Decimal('1500.00000000'),
            cpp_pen=Decimal('15.00000000')
        )
        self.assertIsNotNone(detalle.id)
        self.assertEqual(cierre.detalles.count(), 1)

    def test_cierre_periodo_version_unica(self):
        from apps.empresas.models import CierrePeriodo

        CierrePeriodo.objects.create(
            periodo=self.periodo,
            version_calculo=1,
            cerrado_por=self.usuario
        )

        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                CierrePeriodo.objects.create(
                    periodo=self.periodo,
                    version_calculo=1,
                    cerrado_por=self.usuario
                )

    def test_cierre_detalle_unicidad_producto_establecimiento(self):
        from apps.empresas.models import CierrePeriodo, CierrePeriodoDetalle

        cierre = CierrePeriodo.objects.create(
            periodo=self.periodo,
            version_calculo=1,
            cerrado_por=self.usuario
        )
        CierrePeriodoDetalle.objects.create(
            cierre_periodo=cierre,
            producto=self.producto,
            establecimiento=self.establecimiento,
            saldo_cantidad=Decimal('50.00000000')
        )

        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                CierrePeriodoDetalle.objects.create(
                    cierre_periodo=cierre,
                    producto=self.producto,
                    establecimiento=self.establecimiento,
                    saldo_cantidad=Decimal('80.00000000')
                )


class CierrePeriodoServiceTest(TestCase):
    def setUp(self):
        import datetime
        self.moneda = Moneda.objects.create(codigo='PEN', nombre='Soles')
        self.empresa = Empresa.objects.create(ruc='20999999991', razon_social='CIERRES SAC', moneda_base_codigo=self.moneda)
        self.establecimiento = Establecimiento.objects.create(empresa=self.empresa, codigo_sunat='0000', nombre='Principal')
        ConfigEmpresa.objects.create(empresa=self.empresa, tolerancia_residuo_pen=Decimal('0.05'), decimales_calculo=6, establecimiento_principal=self.establecimiento)
        self.usuario = Usuario.objects.create(username='cierre_service', email='service@factkard.local', password_hash='hash')
        self.periodo = Periodo.objects.create(empresa=self.empresa, anio=2026, mes=1, orden=202601, fecha_inicio=datetime.date(2026,1,1), fecha_fin=datetime.date(2026,1,31))

    def test_01_hash_es_determinista(self):
        resumen = {'b': 2, 'a': 1}; detalles = [{'producto_id': 2, 'establecimiento_id': 1}, {'producto_id': 1, 'establecimiento_id': 1}]
        self.assertEqual(calcular_hash_cierre(resumen, detalles), calcular_hash_cierre(resumen, list(reversed(detalles))))

    def test_02_hash_cambia_con_resumen(self):
        self.assertNotEqual(calcular_hash_cierre({'a': 1}, []), calcular_hash_cierre({'a': 2}, []))

    def test_03_cierre_vacio_crea_snapshot(self):
        cierre, avisos = cerrar_periodo(empresa_id=self.empresa.id, periodo_id=self.periodo.id, usuario=self.usuario)
        self.assertEqual((cierre.version_calculo, cierre.detalles.count(), avisos), (1, 0, []))

    def test_04_cierre_marca_periodo_cerrado(self):
        cerrar_periodo(empresa_id=self.empresa.id, periodo_id=self.periodo.id, usuario=self.usuario); self.periodo.refresh_from_db()
        self.assertEqual(self.periodo.estado, 'CERRADO')

    def test_05_cierre_archivo_excel_nulo(self):
        cierre, _ = cerrar_periodo(empresa_id=self.empresa.id, periodo_id=self.periodo.id, usuario=self.usuario)
        self.assertIsNone(cierre.archivo_excel)

    def test_06_cierre_hash_sha256(self):
        cierre, _ = cerrar_periodo(empresa_id=self.empresa.id, periodo_id=self.periodo.id, usuario=self.usuario)
        self.assertEqual(len(cierre.hash_resultado), 64)

    def test_07_no_cierra_dos_veces_sin_reabrir(self):
        cerrar_periodo(empresa_id=self.empresa.id, periodo_id=self.periodo.id, usuario=self.usuario)
        with self.assertRaises(ValidationError): cerrar_periodo(empresa_id=self.empresa.id, periodo_id=self.periodo.id, usuario=self.usuario)

    def test_08_bloquea_periodo_anterior_abierto(self):
        import datetime
        anterior = Periodo.objects.create(empresa=self.empresa, anio=2025, mes=12, orden=202512, fecha_inicio=datetime.date(2025,12,1), fecha_fin=datetime.date(2025,12,31))
        with self.assertRaises(ValidationError): cerrar_periodo(empresa_id=self.empresa.id, periodo_id=self.periodo.id, usuario=self.usuario)
        self.assertEqual(anterior.estado, 'ABIERTO')

    def test_09_bloquea_periodo_anterior_desactualizado(self):
        import datetime
        Periodo.objects.create(empresa=self.empresa, anio=2025, mes=12, orden=202512, fecha_inicio=datetime.date(2025,12,1), fecha_fin=datetime.date(2025,12,31), estado='DESACTUALIZADO')
        with self.assertRaises(ValidationError): cerrar_periodo(empresa_id=self.empresa.id, periodo_id=self.periodo.id, usuario=self.usuario)

    def test_10_bloquea_incidencia_pendiente(self):
        Incidencia.objects.create(empresa=self.empresa, periodo=self.periodo, tipo='PRUEBA', descripcion='Bloqueante')
        with self.assertRaises(ValidationError): cerrar_periodo(empresa_id=self.empresa.id, periodo_id=self.periodo.id, usuario=self.usuario)

    def test_11_permite_incidencia_resuelta(self):
        Incidencia.objects.create(empresa=self.empresa, periodo=self.periodo, tipo='PRUEBA', descripcion='Resuelta', estado='RESUELTA')
        cierre, _ = cerrar_periodo(empresa_id=self.empresa.id, periodo_id=self.periodo.id, usuario=self.usuario)
        self.assertTrue(cierre.vigente)

    def test_12_reapertura_preserva_cierre(self):
        cierre, _ = cerrar_periodo(empresa_id=self.empresa.id, periodo_id=self.periodo.id, usuario=self.usuario)
        reabrir_periodo(empresa_id=self.empresa.id, periodo_id=self.periodo.id, usuario=self.usuario, motivo='Corrección documentada')
        self.assertTrue(CierrePeriodo.objects.filter(id=cierre.id).exists())

    def test_13_nuevo_cierre_incrementa_version_e_invalida_anterior(self):
        primero, _ = cerrar_periodo(empresa_id=self.empresa.id, periodo_id=self.periodo.id, usuario=self.usuario)
        reabrir_periodo(empresa_id=self.empresa.id, periodo_id=self.periodo.id, usuario=self.usuario, motivo='Corrección documentada')
        segundo, _ = cerrar_periodo(empresa_id=self.empresa.id, periodo_id=self.periodo.id, usuario=self.usuario); primero.refresh_from_db()
        self.assertEqual(segundo.version_calculo, 2); self.assertFalse(primero.vigente)

    def test_14_reapertura_desactualiza_periodos_posteriores(self):
        import datetime
        cerrar_periodo(empresa_id=self.empresa.id, periodo_id=self.periodo.id, usuario=self.usuario)
        posterior = Periodo.objects.create(empresa=self.empresa, anio=2026, mes=2, orden=202602, fecha_inicio=datetime.date(2026,2,1), fecha_fin=datetime.date(2026,2,28), estado='CERRADO')
        _, total = reabrir_periodo(empresa_id=self.empresa.id, periodo_id=self.periodo.id, usuario=self.usuario, motivo='Corrección documentada'); posterior.refresh_from_db()
        self.assertEqual((total, posterior.estado), (1, 'DESACTUALIZADO'))
