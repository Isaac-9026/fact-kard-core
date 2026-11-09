"""
Bloque 17C — consulta de datos fiscales por RUC (ayuda para autocompletar formularios).

Capa desacoplada: `service.consultar_ruc()` valida el RUC (reutiliza el Catálogo 06 y el
dígito verificador del Bloque 16), consulta a un PROVEEDOR intercambiable, normaliza la
respuesta y la cachea un tiempo. Ver providers.py para el estado de la fuente oficial.

No es un módulo de empresas ni de terceros: solo devuelve datos; quien los guarda es el
formulario existente (Empresa / Datos fiscales / Tercero), después de que el usuario revisa.
"""
