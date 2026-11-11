"""
Pruebas unitarias para la arquitectura en cascada de extracción OCR (Gemini 2.5 Flash + Fallback local).
Verifica:
1. Extracción IA exitosa simulada (mock), mapeo exacto de campos y tipos Decimal (cero floats).
2. Resiliencia ante error de red (URLError/timeout) sin lanzar excepciones 500.
3. Cero llamadas de red si GEMINI_API_KEY no está configurada o si texto_ocr viene explícito.
"""
import io
import json
import urllib.error
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase, override_settings

from apps.documentos.captura_services import extraer_ocr_basico


class OcrGeminiCascadaTests(SimpleTestCase):
    def setUp(self):
        self.imagen_fake_bytes = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
        self.gemini_json_factura = {
            "ruc_emisor": "20601234567",
            "razon_social_emisor": "DISTRIBUIDORA INDUSTRIAL FERRETERA SAC",
            "ruc_cliente": "20555000111",
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
        self.assertEqual(cab["ruc_emisor"], ("20601234567", Decimal("98.0000")))
        self.assertEqual(cab["razon_social_emisor"], ("DISTRIBUIDORA INDUSTRIAL FERRETERA SAC", Decimal("94.0000")))
        self.assertEqual(cab["ruc_cliente"], ("20555000111", Decimal("92.0000")))
        self.assertEqual(cab["tipo_comprobante"], ("01", Decimal("98.0000")))
        self.assertEqual(cab["serie"], ("F001", Decimal("98.0000")))
        self.assertEqual(cab["numero"], ("450", Decimal("98.0000")))
        self.assertEqual(cab["serie_numero"], ("F001-450", Decimal("98.0000")))
        self.assertEqual(cab["fecha_emision"], ("2026-03-15", Decimal("96.0000")))
        self.assertEqual(cab["moneda"], ("PEN", Decimal("96.0000")))
        self.assertEqual(cab["subtotal"][0], "200.00000000")
        self.assertEqual(cab["igv"][0], "36.00000000")
        self.assertEqual(cab["total"][0], "236.00000000")

        # Confianza global
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
        self.assertEqual(item["precio_unitario"], Decimal("118.00000000"))
        self.assertIsInstance(item["valor_total"], Decimal)
        self.assertEqual(item["valor_total"], Decimal("200.00000000"))
        self.assertIsInstance(item["confianza"], Decimal)

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

        # No debe lanzar excepción y debe retornar estructura válida
        self.assertEqual(resultado["tipo"], "OCR")
        self.assertIn("cabecera", resultado)
        self.assertIn("detalles", resultado)
        # Debe registrar una alerta explicativa
        alertas = resultado.get("alertas", [])
        self.assertTrue(len(alertas) >= 1)
        self.assertIn("Fallo en extracción multimodal Gemini", alertas[0])
        # Confianza baja del fallback
        self.assertEqual(resultado["cabecera"]["ruc_emisor"][1], Decimal("0.0000"))

    @override_settings(GEMINI_API_KEY="")
    @patch("urllib.request.urlopen")
    def test_sin_api_key_no_intenta_llamada_red(self, mock_urlopen):
        """Sin GEMINI_API_KEY configurada, jamás se intenta llamada HTTP externa."""
        resultado = extraer_ocr_basico(
            content=b"FACTURA F001-000100 RUC 20123456789 TOTAL: 100.00",
            filename="factura.png",
            texto_ocr=None,
        )

        mock_urlopen.assert_not_called()
        self.assertEqual(resultado["tipo"], "OCR")
        # El parser local de expresiones regulares extrae los datos offline
        self.assertEqual(resultado["cabecera"]["ruc_emisor"][0], "20123456789")
        self.assertEqual(resultado["cabecera"]["serie"][0], "F001")

    @override_settings(GEMINI_API_KEY="test-api-key-gemini")
    @patch("urllib.request.urlopen")
    def test_texto_ocr_explicito_tiene_prioridad_nivel_1(self, mock_urlopen):
        """Si texto_ocr fue provisto explícitamente (ej. tests existentes), corre Nivel 1 sin llamar a red."""
        texto_test = "FACTURA F001-000099 RUC 20555000111 TOTAL: 50.00"
        resultado = extraer_ocr_basico(
            content=b"",
            filename="cualquiera.pdf",
            texto_ocr=texto_test,
        )

        mock_urlopen.assert_not_called()
        self.assertEqual(resultado["cabecera"]["ruc_emisor"][0], "20555000111")
        self.assertEqual(resultado["cabecera"]["serie"][0], "F001")
        self.assertEqual(resultado["cabecera"]["numero"][0], "000099")


class OcrGeminiApiUploadIntegrationTests(TestCase):
    """Pruebas adicionales de integración del endpoint de subida de captura."""

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
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps.documentos.captura_services import procesar_subida_captura
        from apps.documentos.models import CapturaCampo, DocumentoCaptura
        from apps.empresas.models import Empresa
        from apps.usuarios.models import Usuario

        gemini_json_factura = {
            "ruc_emisor": "20601234567",
            "razon_social_emisor": "FERRETERIA CENTRAL SAC",
            "ruc_cliente": "20555000111",
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
                    "precio_unitario": "40.00",
                    "importe_total": "200.00"
                }
            ],
            "confianza": 95
        }
        mock_urlopen.return_value = self._crear_http_response_mock(gemini_json_factura)

        from apps.catalogos.models import Moneda
        moneda_pen, _ = Moneda.objects.get_or_create(
            codigo="PEN",
            defaults={"nombre": "Soles"},
        )
        empresa = Empresa.objects.create(
            ruc="20555000111",
            razon_social="MI EMPRESA SAC",
            nombre_comercial="MI EMPRESA",
            direccion="AV. PRINCIPAL 123",
            departamento="LIMA",
            provincia="LIMA",
            distrito="LIMA",
            ubigeo="150101",
            moneda_base_codigo=moneda_pen,
        )
        usuario = Usuario.objects.create(
            username="test_ai_user",
            email="test_ai@example.com",
            password_hash="test_hash",
            activo=True,
        )

        archivo = SimpleUploadedFile(
            "factura_ferreteria.jpg",
            b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00',
            content_type="image/jpeg",
        )

        captura, creada = procesar_subida_captura(
            empresa_id=empresa.id,
            usuario=usuario,
            archivo=archivo,
            tipo="IMAGEN",
        )

        self.assertTrue(creada)
        self.assertEqual(captura.tipo, "IMAGEN")
        
        campos_dict = {
            c.nombre_campo: c.valor_extraido
            for c in CapturaCampo.objects.filter(documento_captura=captura, seccion="CABECERA")
        }
        self.assertEqual(campos_dict.get("ruc_emisor"), "20601234567")
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

