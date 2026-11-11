"""
Pruebas unitarias y de integración para la arquitectura de extracción OCR con Gemini y motor de validación contable.
Verifica:
1. Extracción IA exitosa con validación estricta de RUC (módulo 11), cuadre de líneas y cuadre de totales.
2. Detección y castigo de RUC inválido (ej. '20258963241') reduciendo confianza a 50.0000 y emitiendo alertas.
3. Normalización fiel de serie y número: respeta series físicas (ej. '001') sin inventar letras 'F', y aísla números estrictamente a dígitos (sin guiones).
4. Desglose y cuadre de líneas: resuelve valor unitario sin IGV cuando el comprobante indica precio con IGV y total sin IGV.
5. Detección de líneas incoherentes y totales descuadrados con reducción de confianza a rojo.
6. Protección del Kardex: 'generar_borrador_desde_captura' bloquea la generación si los datos no cuadran o el RUC es inválido, permitiéndola una vez corregidos.
7. Resiliencia ante caídas de red y cero floats en todas las operaciones.
"""
import datetime
import json
import urllib.error
from decimal import Decimal
from unittest.mock import MagicMock, patch

from rest_framework.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings

from apps.catalogos.models import Moneda, TipoComprobante, TipoOperacion
from apps.documentos.captura_services import (
    extraer_ocr_basico,
    generar_borrador_desde_captura,
    procesar_subida_captura,
)
from apps.documentos.models import CapturaCampo, DocumentoCaptura
from apps.empresas.models import Empresa, Establecimiento, Periodo
from apps.inventario.models import Almacen, Producto
from apps.usuarios.models import Usuario


class OcrGeminiCascadaTests(SimpleTestCase):
    def setUp(self):
        self.imagen_fake_bytes = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
        # 20600900855 y 20454439491 son RUCs reales peruanos válidos bajo algoritmo módulo 11
        self.gemini_json_factura = {
            "ruc_emisor": "20600900855",
            "razon_social_emisor": "DISTRIBUIDORA INDUSTRIAL FERRETERA SAC",
            "ruc_cliente": "20454439491",
            "razon_social_cliente": "CONSTRUCTORA LIMA SUR SAC",
            "tipo_comprobante": "01",
            "serie": "F001",
            "numero": "000450",
            "fecha_emision": "2026-03-15",
            "moneda": "PEN",
            "subtotal": "200.00",
            "igv": "36.00",
            "total": "236.00",
            "afectacion_igv": "GRAVADO",
            "items": [
                {
                    "codigo": "SKU-HERR-01",
                    "descripcion": "TALADRO PERCUTOR 650W",
                    "unidad_medida": "NIU",
                    "cantidad": "2.00",
                    "valor_unitario": "100.00",
                    "precio_unitario": "118.00",
                    "importe_total": "200.00"
                }
            ],
            "confianza": 98
        }

    def _crear_http_response_mock(self, datos_json: dict) -> MagicMock:
        body = json.dumps({
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": json.dumps(datos_json)}
                        ]
                    }
                }
            ]
        }).encode("utf-8")
        resp = MagicMock()
        resp.read.return_value = body
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = None
        return resp

    @override_settings(GEMINI_API_KEY="test-api-key-gemini", GEMINI_MODEL="gemini-2.5-flash")
    @patch("urllib.request.urlopen")
    def test_extraccion_ia_exitosa_mocked(self, mock_urlopen):
        """Simula respuesta HTTP exitosa de Gemini y verifica mapeo fiel con Decimal y alta confianza."""
        mock_urlopen.return_value = self._crear_http_response_mock(self.gemini_json_factura)

        resultado = extraer_ocr_basico(
            content=self.imagen_fake_bytes,
            filename="factura_foto.jpg",
            texto_ocr=None,
        )

        self.assertTrue(mock_urlopen.called)
        self.assertEqual(resultado["tipo"], "OCR")

        # Cabecera
        cab = resultado["cabecera"]
        self.assertEqual(cab["ruc_emisor"], ("20600900855", Decimal("98.0000")))
        self.assertEqual(cab["razon_social_emisor"], ("DISTRIBUIDORA INDUSTRIAL FERRETERA SAC", Decimal("94.0000")))
        self.assertEqual(cab["ruc_cliente"], ("20454439491", Decimal("95.0000")))
        self.assertEqual(cab["tipo_comprobante"], ("01", Decimal("98.0000")))
        self.assertEqual(cab["serie"], ("F001", Decimal("98.0000")))
        self.assertEqual(cab["numero"], ("450", Decimal("98.0000")))
        self.assertEqual(cab["serie_numero"], ("F001-450", Decimal("98.0000")))
        self.assertEqual(cab["fecha_emision"], ("2026-03-15", Decimal("96.0000")))
        self.assertEqual(cab["moneda"], ("PEN", Decimal("96.0000")))
        self.assertEqual(cab["subtotal"][0], "200.00000000")
        self.assertEqual(cab["igv"][0], "36.00000000")
        self.assertEqual(cab["total"][0], "236.00000000")

        # Confianza global alta y sin alertas de error
        self.assertEqual(resultado["confianza_global"], Decimal("95.0000"))
        self.assertEqual(resultado.get("alertas"), [])

        # Detalle / Líneas
        detalles = resultado["detalles"]
        self.assertEqual(len(detalles), 1)
        item = detalles[0]
        self.assertEqual(item["numero_linea"], 1)
        self.assertEqual(item["codigo_externo"], "SKU-HERR-01")
        self.assertEqual(item["descripcion"], "TALADRO PERCUTOR 650W")
        self.assertEqual(item["unidad_medida"], "NIU")
        self.assertEqual(item["afectacion_igv"], "GRAVADO")

        # Cero floats: todos los montos deben ser estrictamente Decimal
        self.assertIsInstance(item["cantidad"], Decimal)
        self.assertEqual(item["cantidad"], Decimal("2.00000000"))
        self.assertIsInstance(item["precio_unitario"], Decimal)
        self.assertEqual(item["precio_unitario"], Decimal("100.00000000"))
        self.assertIsInstance(item["valor_total"], Decimal)
        self.assertEqual(item["valor_total"], Decimal("200.00000000"))
        self.assertIsInstance(item["confianza"], Decimal)

    @override_settings(GEMINI_API_KEY="test-api-key-gemini")
    @patch("urllib.request.urlopen")
    def test_ruc_invalido_modulo_11_reduce_confianza_y_emite_alerta(self, mock_urlopen):
        """Un RUC falso como '20258963241' debe ser castigado a 50% de confianza con alerta contable."""
        datos = dict(self.gemini_json_factura)
        datos["ruc_emisor"] = "20258963241"  # No pasa módulo 11
        mock_urlopen.return_value = self._crear_http_response_mock(datos)

        resultado = extraer_ocr_basico(
            content=self.imagen_fake_bytes,
            filename="factura_ruc_falso.jpg",
            texto_ocr=None,
        )

        cab = resultado["cabecera"]
        self.assertEqual(cab["ruc_emisor"][1], Decimal("50.0000"))
        self.assertEqual(resultado["confianza_global"], Decimal("50.0000"))
        alertas = resultado.get("alertas", [])
        self.assertTrue(any("módulo 11" in a for a in alertas))

    @override_settings(GEMINI_API_KEY="test-api-key-gemini")
    @patch("urllib.request.urlopen")
    def test_serie_fisica_sin_inventar_letra_y_numero_limpio(self, mock_urlopen):
        """Una factura física '001-201' no debe inventar 'F' y el número debe quedar solo con dígitos."""
        datos = dict(self.gemini_json_factura)
        datos["serie"] = "001"
        datos["numero"] = "1-201"
        datos["serie_numero"] = "001-201"
        mock_urlopen.return_value = self._crear_http_response_mock(datos)

        resultado = extraer_ocr_basico(
            content=self.imagen_fake_bytes,
            filename="factura_fisica.jpg",
            texto_ocr=None,
        )

        cab = resultado["cabecera"]
        self.assertEqual(cab["serie"][0], "001")
        self.assertEqual(cab["numero"][0], "201")
        self.assertEqual(cab["serie_numero"][0], "001-201")

    @override_settings(GEMINI_API_KEY="test-api-key-gemini")
    @patch("urllib.request.urlopen")
    def test_cuadre_de_linea_resuelve_valor_unitario_sin_igv(self, mock_urlopen):
        """Si la foto tiene cantidad 10, precio unitario 21.24 (con IGV) y total 180 (sin IGV), calcula 18.00."""
        datos = dict(self.gemini_json_factura)
        datos["subtotal"] = "180.00"
        datos["igv"] = "32.40"
        datos["total"] = "212.40"
        datos["items"] = [
            {
                "codigo": "P-01",
                "descripcion": "DISCO DE CORTE",
                "unidad_medida": "NIU",
                "cantidad": "10.00",
                "precio_unitario": "21.24",
                "valor_total": "180.00",
            }
        ]
        mock_urlopen.return_value = self._crear_http_response_mock(datos)

        resultado = extraer_ocr_basico(
            content=self.imagen_fake_bytes,
            filename="factura_desglose.jpg",
            texto_ocr=None,
        )

        item = resultado["detalles"][0]
        # El motor debe resolver el costo unitario sin IGV para el Kardex
        self.assertEqual(item["valor_unitario"], Decimal("18.00000000"))
        self.assertEqual(item["valor_total"], Decimal("180.00000000"))
        self.assertGreaterEqual(item["confianza"], Decimal("90.0000"))

    @override_settings(GEMINI_API_KEY="test-api-key-gemini")
    @patch("urllib.request.urlopen")
    def test_linea_incoherente_reduce_confianza_y_emite_alerta(self, mock_urlopen):
        """Si cantidad * precio no cuadra con el total y no es tema de IGV, baja la confianza a 50% con alerta."""
        datos = dict(self.gemini_json_factura)
        datos["items"] = [
            {
                "codigo": "P-01",
                "descripcion": "ARTICULO DESCUADRADO",
                "unidad_medida": "NIU",
                "cantidad": "10.00",
                "precio_unitario": "50.00",
                "valor_total": "180.00",
            }
        ]
        mock_urlopen.return_value = self._crear_http_response_mock(datos)

        resultado = extraer_ocr_basico(
            content=self.imagen_fake_bytes,
            filename="factura_descuadrada.jpg",
            texto_ocr=None,
        )

        item = resultado["detalles"][0]
        self.assertEqual(item["confianza"], Decimal("50.0000"))
        self.assertEqual(resultado["confianza_global"], Decimal("50.0000"))
        self.assertTrue(any("Incoherencia" in a or "no cuadra" in a for a in resultado.get("alertas", [])))

    @override_settings(GEMINI_API_KEY="test-api-key-gemini")
    @patch("urllib.request.urlopen")
    def test_totales_descuadrados_reduce_confianza_y_emite_alerta(self, mock_urlopen):
        """Si subtotal + igv != total, se baja la confianza del total a 50% y se genera alerta."""
        datos = dict(self.gemini_json_factura)
        datos["subtotal"] = "200.00"
        datos["igv"] = "36.00"
        datos["total"] = "299.99"  # Descuadre evidente
        mock_urlopen.return_value = self._crear_http_response_mock(datos)

        resultado = extraer_ocr_basico(
            content=self.imagen_fake_bytes,
            filename="factura_totales_mal.jpg",
            texto_ocr=None,
        )

        cab = resultado["cabecera"]
        self.assertEqual(cab["total"][1], Decimal("50.0000"))
        self.assertEqual(resultado["confianza_global"], Decimal("50.0000"))
        self.assertTrue(any("no cuadra con subtotal" in a for a in resultado.get("alertas", [])))

    @override_settings(GEMINI_API_KEY="test-api-key-gemini")
    @patch("urllib.request.urlopen")
    def test_resiliencia_error_red_gemini_fallback_local(self, mock_urlopen):
        """Si la API de Gemini lanza URLError o Timeout, no lanza 500 sino que cae a Nivel 3 con alerta."""
        mock_urlopen.side_effect = urllib.error.URLError("Connection timed out")

        resultado = extraer_ocr_basico(
            content=b"Contenido simulado no interpretable",
            filename="comprobante_escaneado.png",
            texto_ocr=None,
        )

        self.assertEqual(resultado["tipo"], "OCR")
        self.assertIn("cabecera", resultado)
        self.assertIn("detalles", resultado)
        alertas = resultado.get("alertas", [])
        self.assertTrue(len(alertas) >= 1)
        self.assertIn("Fallo en extracción multimodal Gemini", alertas[0])
        self.assertEqual(resultado["cabecera"]["ruc_emisor"][1], Decimal("0.0000"))

    @override_settings(GEMINI_API_KEY="")
    @patch("urllib.request.urlopen")
    def test_sin_api_key_no_intenta_llamada_red(self, mock_urlopen):
        """Sin GEMINI_API_KEY configurada, jamás se intenta llamada HTTP externa."""
        resultado = extraer_ocr_basico(
            content=b"FACTURA F001-000100 RUC 20600900855 TOTAL: 100.00",
            filename="factura.png",
            texto_ocr=None,
        )

        mock_urlopen.assert_not_called()
        self.assertEqual(resultado["tipo"], "OCR")
        self.assertEqual(resultado["cabecera"]["ruc_emisor"][0], "20600900855")
        self.assertEqual(resultado["cabecera"]["serie"][0], "F001")

    @override_settings(GEMINI_API_KEY="test-api-key-gemini")
    @patch("urllib.request.urlopen")
    def test_texto_ocr_explicito_tiene_prioridad_nivel_1(self, mock_urlopen):
        """Si texto_ocr fue provisto explícitamente, corre Nivel 1 sin llamar a red."""
        texto_test = "FACTURA F001-000099 RUC 20600900855 TOTAL: 50.00"
        resultado = extraer_ocr_basico(
            content=b"",
            filename="cualquiera.pdf",
            texto_ocr=texto_test,
        )

        mock_urlopen.assert_not_called()
        self.assertEqual(resultado["cabecera"]["ruc_emisor"][0], "20600900855")
        self.assertEqual(resultado["cabecera"]["serie"][0], "F001")
        self.assertEqual(resultado["cabecera"]["numero"][0], "000099")


class OcrGeminiApiUploadIntegrationTests(TestCase):
    """Pruebas de integración del flujo de subida de captura y generación protegida de borrador."""

    def setUp(self):
        self.moneda_pen, _ = Moneda.objects.get_or_create(
            codigo="PEN",
            defaults={"nombre": "Soles"},
        )
        self.empresa = Empresa.objects.create(
            ruc="20454439491",
            razon_social="MI EMPRESA SAC",
            nombre_comercial="MI EMPRESA",
            direccion="AV. PRINCIPAL 123",
            departamento="LIMA",
            provincia="LIMA",
            distrito="LIMA",
            ubigeo="150101",
            moneda_base_codigo=self.moneda_pen,
        )
        self.usuario = Usuario.objects.create(
            username="test_ai_user",
            email="test_ai@example.com",
            password_hash="test_hash",
            activo=True,
        )
        self.establecimiento = Establecimiento.objects.create(
            empresa=self.empresa,
            codigo_sunat="0000",
            nombre="Principal",
            activo=True,
        )
        self.almacen = Almacen.objects.create(
            empresa=self.empresa,
            establecimiento=self.establecimiento,
            codigo="ALM-01",
            nombre="Almacén Central",
            activo=True,
        )
        self.tipo_comp, _ = TipoComprobante.objects.get_or_create(
            codigo_sunat="01",
            defaults={"descripcion": "FACTURA", "activo": True},
        )
        self.tipo_op, _ = TipoOperacion.objects.get_or_create(
            codigo_interno="COMPRA",
            defaults={
                "codigo_sunat": "02",
                "descripcion": "COMPRA NACIONAL",
                "naturaleza": "ENTRADA",
                "origen_requerido": "DOCUMENTO",
                "afecta_kardex": True,
                "activo": True,
            },
        )
        self.periodo = Periodo.objects.create(
            empresa=self.empresa,
            anio=2026,
            mes=3,
            orden=202603,
            fecha_inicio=datetime.date(2026, 3, 1),
            fecha_fin=datetime.date(2026, 3, 31),
            estado="ABIERTO",
        )

    def _crear_http_response_mock(self, datos_json: dict) -> MagicMock:
        body = json.dumps({
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": json.dumps(datos_json)}
                        ]
                    }
                }
            ]
        }).encode("utf-8")
        resp = MagicMock()
        resp.read.return_value = body
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = None
        return resp

    @override_settings(GEMINI_API_KEY="test-api-key-gemini")
    @patch("urllib.request.urlopen")
    def test_subida_captura_imagen_mock_gemini_crea_campos_correctamente(self, mock_urlopen):
        """Verifica que procesar_subida_captura pueble CapturaCampo con los datos de Gemini."""
        gemini_json_factura = {
            "ruc_emisor": "20600900855",
            "razon_social_emisor": "FERRETERIA CENTRAL SAC",
            "ruc_cliente": "20454439491",
            "tipo_comprobante": "01",
            "serie": "F001",
            "numero": "000450",
            "fecha_emision": "2026-03-15",
            "moneda": "PEN",
            "subtotal": "200.00",
            "igv": "36.00",
            "total": "236.00",
            "afectacion_igv": "GRAVADO",
            "items": [
                {
                    "codigo": "SKU-01",
                    "descripcion": "CEMENTO SOL",
                    "unidad_medida": "NIU",
                    "cantidad": "5.00",
                    "valor_unitario": "40.00",
                    "precio_unitario": "47.20",
                    "importe_total": "200.00"
                }
            ],
            "confianza": 95
        }
        mock_urlopen.return_value = self._crear_http_response_mock(gemini_json_factura)

        archivo = SimpleUploadedFile(
            "factura_ferreteria.jpg",
            b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00',
            content_type="image/jpeg",
        )

        captura, creada = procesar_subida_captura(
            empresa_id=self.empresa.id,
            usuario=self.usuario,
            archivo=archivo,
            tipo="IMAGEN",
        )

        self.assertTrue(creada)
        self.assertEqual(captura.tipo, "IMAGEN")

        campos_dict = {
            c.nombre_campo: c.valor_extraido
            for c in CapturaCampo.objects.filter(documento_captura=captura, seccion="CABECERA")
        }
        self.assertEqual(campos_dict.get("ruc_emisor"), "20600900855")
        self.assertEqual(campos_dict.get("serie"), "F001")
        self.assertEqual(campos_dict.get("numero"), "450")
        self.assertEqual(campos_dict.get("total"), "236.00000000")

        detalle_campo = CapturaCampo.objects.filter(
            documento_captura=captura,
            seccion="DETALLE",
            nombre_campo="codigo_externo",
        ).first()
        self.assertIsNotNone(detalle_campo)
        self.assertEqual(detalle_campo.valor_extraido, "SKU-01")

    def test_generar_borrador_rechaza_ruc_invalido_modulo_11(self):
        """Bloquea la generación de borrador si el RUC emisor no pasa el módulo 11 de SUNAT."""
        captura = DocumentoCaptura.objects.create(
            empresa=self.empresa,
            subido_por=self.usuario,
            ruta_archivo="fake_ruc_inv.jpg",
            tipo="IMAGEN",
            hash_sha256="fake_sha256_ruc_invalido",
            estado_proceso="PENDIENTE",
        )
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="tipo_comprobante", valor_extraido="01")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="serie", valor_extraido="F001")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="numero", valor_extraido="100")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="ruc_emisor", valor_extraido="20258963241")  # Falso
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="ruc_cliente", valor_extraido="20454439491")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="moneda", valor_extraido="PEN")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="fecha_emision", valor_extraido="2026-03-15")

        with self.assertRaises(ValidationError) as ctx:
            generar_borrador_desde_captura(
                captura_id=captura.id,
                empresa_id=self.empresa.id,
                usuario=self.usuario,
                almacen_id=self.almacen.id,
            )

        self.assertIn("módulo 11", str(ctx.exception))

    def test_generar_borrador_rechaza_linea_descuadrada(self):
        """Bloquea la generación si una línea no cuadra cantidad x precio = total."""
        captura = DocumentoCaptura.objects.create(
            empresa=self.empresa,
            subido_por=self.usuario,
            ruta_archivo="fake_linea_desc.jpg",
            tipo="IMAGEN",
            hash_sha256="fake_sha256_linea_descuadrada",
            estado_proceso="PENDIENTE",
        )
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="tipo_comprobante", valor_extraido="01")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="serie", valor_extraido="F001")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="numero", valor_extraido="100")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="ruc_emisor", valor_extraido="20600900855")  # Válido
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="ruc_cliente", valor_extraido="20454439491")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="moneda", valor_extraido="PEN")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="fecha_emision", valor_extraido="2026-03-15")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="subtotal", valor_extraido="180.00")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="igv", valor_extraido="32.40")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="total", valor_extraido="212.40")

        # Línea descuadrada: 10 x 50 != 180
        CapturaCampo.objects.create(documento_captura=captura, seccion="DETALLE", numero_linea=1, nombre_campo="descripcion", valor_extraido="Item A")
        CapturaCampo.objects.create(documento_captura=captura, seccion="DETALLE", numero_linea=1, nombre_campo="cantidad", valor_extraido="10.00")
        CapturaCampo.objects.create(documento_captura=captura, seccion="DETALLE", numero_linea=1, nombre_campo="precio_unitario", valor_extraido="50.00")
        CapturaCampo.objects.create(documento_captura=captura, seccion="DETALLE", numero_linea=1, nombre_campo="valor_total", valor_extraido="180.00")

        with self.assertRaises(ValidationError) as ctx:
            generar_borrador_desde_captura(
                captura_id=captura.id,
                empresa_id=self.empresa.id,
                usuario=self.usuario,
                almacen_id=self.almacen.id,
            )

        self.assertIn("descuadre", str(ctx.exception))

    def test_generar_borrador_rechaza_totales_descuadrados(self):
        """Bloquea la generación si subtotal + igv != total."""
        captura = DocumentoCaptura.objects.create(
            empresa=self.empresa,
            subido_por=self.usuario,
            ruta_archivo="fake_totales_desc.jpg",
            tipo="IMAGEN",
            hash_sha256="fake_sha256_totales_descuadrados",
            estado_proceso="PENDIENTE",
        )
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="tipo_comprobante", valor_extraido="01")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="serie", valor_extraido="F001")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="numero", valor_extraido="100")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="ruc_emisor", valor_extraido="20600900855")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="ruc_cliente", valor_extraido="20454439491")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="moneda", valor_extraido="PEN")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="fecha_emision", valor_extraido="2026-03-15")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="subtotal", valor_extraido="100.00")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="igv", valor_extraido="18.00")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="total", valor_extraido="150.00")  # Descuadrado

        # Línea cuadrada: 1 x 100 = 100
        CapturaCampo.objects.create(documento_captura=captura, seccion="DETALLE", numero_linea=1, nombre_campo="descripcion", valor_extraido="Item A")
        CapturaCampo.objects.create(documento_captura=captura, seccion="DETALLE", numero_linea=1, nombre_campo="cantidad", valor_extraido="1.00")
        CapturaCampo.objects.create(documento_captura=captura, seccion="DETALLE", numero_linea=1, nombre_campo="precio_unitario", valor_extraido="100.00")
        CapturaCampo.objects.create(documento_captura=captura, seccion="DETALLE", numero_linea=1, nombre_campo="valor_total", valor_extraido="100.00")

        with self.assertRaises(ValidationError) as ctx:
            generar_borrador_desde_captura(
                captura_id=captura.id,
                empresa_id=self.empresa.id,
                usuario=self.usuario,
                almacen_id=self.almacen.id,
            )

        self.assertIn("no cuadran", str(ctx.exception))

    def test_generar_borrador_exitoso_cuando_datos_son_validos_y_cuadrados(self):
        """Permite generar el comprobante en borrador cuando los datos son válidos y cuadran contablemente."""
        captura = DocumentoCaptura.objects.create(
            empresa=self.empresa,
            subido_por=self.usuario,
            ruta_archivo="fake_valido.jpg",
            tipo="IMAGEN",
            hash_sha256="fake_sha256_valido_completo",
            estado_proceso="PENDIENTE",
        )
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="tipo_comprobante", valor_extraido="01")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="serie", valor_extraido="001")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="numero", valor_extraido="201")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="ruc_emisor", valor_extraido="20600900855")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="ruc_cliente", valor_extraido="20454439491")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="moneda", valor_extraido="PEN")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="razon_social_emisor", valor_extraido="PROVEEDOR MODELO SAC")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="fecha_emision", valor_extraido="2026-03-15")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="subtotal", valor_extraido="180.00")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="igv", valor_extraido="32.40")
        CapturaCampo.objects.create(documento_captura=captura, seccion="CABECERA", nombre_campo="total", valor_extraido="212.40")

        # Línea cuadrada: 10 x 18 = 180
        CapturaCampo.objects.create(documento_captura=captura, seccion="DETALLE", numero_linea=1, nombre_campo="descripcion", valor_extraido="HERRAMIENTA MANUAL")
        CapturaCampo.objects.create(documento_captura=captura, seccion="DETALLE", numero_linea=1, nombre_campo="cantidad", valor_extraido="10.00")
        CapturaCampo.objects.create(documento_captura=captura, seccion="DETALLE", numero_linea=1, nombre_campo="precio_unitario", valor_extraido="18.00")
        CapturaCampo.objects.create(documento_captura=captura, seccion="DETALLE", numero_linea=1, nombre_campo="valor_total", valor_extraido="180.00")

        res = generar_borrador_desde_captura(
            captura_id=captura.id,
            empresa_id=self.empresa.id,
            usuario=self.usuario,
            almacen_id=self.almacen.id,
        )

        self.assertIsNotNone(res["documento_id"])
        self.assertEqual(res["serie_numero"], "001-201")
        captura.refresh_from_db()
        self.assertEqual(captura.estado_proceso, "BORRADOR_GENERADO")
