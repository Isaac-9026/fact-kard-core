"""
Resolución segura de la configuración sensible de FACT-KARD (SEC-001).

Reglas:
- Producción (DEBUG=False): SECRET_KEY es obligatoria, no puede ser un valor
  conocido/de ejemplo y debe tener longitud suficiente. ALLOWED_HOSTS no puede
  contener '*'.
- Desarrollo (DEBUG=True) sin SECRET_KEY: se genera una clave aleatoria y se
  guarda en un archivo local ignorado por git, para que no exista ningún
  fallback público y los tokens sobrevivan a los reinicios del autoreload.
- Tests (`manage.py test`) sin SECRET_KEY: clave aleatoria efímera en memoria.
"""
import re
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.core.management.utils import get_random_secret_key
from django.views.debug import SafeExceptionReporterFilter

ENMASCARADO = '[OCULTO]'


class Secreto:
    """Valor sensible que nunca se muestra por accidente (print, logs, repr, errores)."""
    __slots__ = ('_valor',)

    def __init__(self, valor=''):
        self._valor = '' if valor is None else str(valor)

    def revelar(self) -> str:
        return self._valor

    def __bool__(self):
        return bool(self._valor.strip())

    def __str__(self):
        return ENMASCARADO if self._valor else ''

    def __repr__(self):
        return f"Secreto({ENMASCARADO if self._valor else 'vacío'})"

    def __format__(self, spec):
        return format(str(self), spec)

    def __eq__(self, otro):
        if isinstance(otro, Secreto):
            return self._valor == otro._valor
        return self._valor == otro

    def __hash__(self):
        return hash(('Secreto', self._valor))

    def __reduce__(self):
        raise TypeError('Un Secreto no se serializa.')


class FiltroReporteExcepciones(SafeExceptionReporterFilter):
    """Páginas/informes de error de Django: oculta claves, tokens y secretos."""
    hidden_settings = re.compile(
        r'API|TOKEN|KEY|SECRET|PASS|SIGNATURE|HTTP_COOKIE|PASSWORD', flags=re.I)


LONGITUD_MINIMA_SECRET_KEY = 50

# Valores publicados en el repositorio (settings.py y .env.example) en versiones
# anteriores. Nunca deben aceptarse fuera de desarrollo.
SECRET_KEYS_INSEGURAS = frozenset({
    'django-insecure-fact-kard-secret-key-change-in-prod',
    'cambiar_este_secreto_por_uno_seguro',
    'cambiar_esto',
})

MENSAJE_SIN_SECRET_KEY = (
    "SECRET_KEY no está definida. Agrégala a backend/.env "
    "(genera una con: python -c \"from django.core.management.utils import "
    "get_random_secret_key; print(get_random_secret_key())\"). "
    "Para desarrollo local también puedes definir DEBUG=True."
)


def es_secret_key_insegura(valor: str) -> bool:
    return (
        valor in SECRET_KEYS_INSEGURAS
        or valor.startswith('django-insecure')
        or len(valor) < LONGITUD_MINIMA_SECRET_KEY
        or len(set(valor)) < 5  # Bloque 7: mismo criterio que security.W009 de Django
    )


def _clave_desarrollo_persistida(ruta: Path) -> str:
    try:
        existente = ruta.read_text(encoding='utf-8').strip()
    except FileNotFoundError:
        existente = ''
    if existente:
        return existente
    nueva = get_random_secret_key()
    ruta.write_text(nueva, encoding='utf-8')
    return nueva


def resolver_secret_key(*, valor, debug: bool, ejecutando_tests: bool, ruta_clave_dev: Path) -> str:
    valor = (valor or '').strip()

    if valor:
        if not debug and not ejecutando_tests and es_secret_key_insegura(valor):
            raise ImproperlyConfigured(
                'SECRET_KEY es insegura (valor de ejemplo, prefijo django-insecure o menos de '
                f'{LONGITUD_MINIMA_SECRET_KEY} caracteres). Genera una nueva para producción.'
            )
        return valor

    if ejecutando_tests:
        return get_random_secret_key()
    if debug:
        return _clave_desarrollo_persistida(ruta_clave_dev)
    raise ImproperlyConfigured(MENSAJE_SIN_SECRET_KEY)


def resolver_docs_api(*, debug: bool, valor) -> bool:
    """
    Bloque 8 — ¿se publica Swagger/OpenAPI (/api/docs/, /api/schema/)?

    - Sin API_DOCS_ENABLED (vacía): sigue a DEBUG → encendida en desarrollo, apagada en producción.
    - API_DOCS_ENABLED=True/False: decisión explícita e intencional del administrador. En
      producción, si se enciende, la documentación exige usuario autenticado
      (ver permisos_docs_api).
    - Cualquier otro valor es un error de configuración (no se adivina).
    """
    texto = '' if valor is None else str(valor).strip().lower()
    if texto == '':
        return bool(debug)
    if texto in ('true', '1', 'yes', 'on'):
        return True
    if texto in ('false', '0', 'no', 'off'):
        return False
    raise ImproperlyConfigured("API_DOCS_ENABLED debe ser True o False (o quedar vacía para seguir a DEBUG).")


def permisos_docs_api(*, debug: bool) -> list[str]:
    """En desarrollo la documentación es abierta; en producción, solo para usuarios autenticados."""
    if debug:
        return ['rest_framework.permissions.AllowAny']
    return ['rest_framework.permissions.IsAuthenticated']


def validar_allowed_hosts(hosts, *, debug: bool):
    hosts = [h.strip() for h in hosts if h and h.strip()]
    if not debug and '*' in hosts:
        raise ImproperlyConfigured(
            "ALLOWED_HOSTS='*' no está permitido con DEBUG=False. Lista los dominios reales."
        )
    return hosts


# ---------------------------------------------------------------------------
# Bloque 7 — validaciones de la configuración de producción (DEBUG=False).
# ---------------------------------------------------------------------------
from urllib.parse import urlsplit  # noqa: E402

TOKEN_MAX_AGE_PRODUCCION_MAXIMO = 60 * 60 * 24 * 30  # 30 días
SAMESITE_VALIDOS = ('Lax', 'Strict', 'None')
HOSTS_LOCALES = frozenset({'localhost', '127.0.0.1', '::1'})
DB_PASSWORDS_INSEGURAS = frozenset({'cambiar_esto', 'postgres', 'password', 'fact_kard', 'fact_kard_user'})


def _es_origen_local(origen: str) -> bool:
    return (urlsplit(origen).hostname or '') in HOSTS_LOCALES


def validar_configuracion_produccion(
    *,
    debug: bool,
    token_max_age: int,
    cors_origins,
    csrf_trusted_origins,
    session_cookie_secure: bool,
    csrf_cookie_secure: bool,
    sin_https: bool,
    auth_cookie_enabled: bool,
    auth_cookie_secure: bool,
    auth_cookie_samesite: str,
    db_password: str | None = None,
    num_proxies: int | None = None,
    proxy_ssl_header: bool = False,
) -> None:
    """
    Lanza ImproperlyConfigured con TODOS los problemas encontrados. Con DEBUG=True solo se
    validan los valores que nunca son correctos (duración del token, SameSite).

    `sin_https` (PRODUCCION_SIN_HTTPS=True) es una excepción explícita para una intranet
    sin certificado: permite cookies y orígenes http, pero sigue validando lo demás.
    """
    errores = []
    if token_max_age <= 0:
        errores.append('TOKEN_MAX_AGE_SECONDS debe ser mayor que 0.')
    if auth_cookie_samesite not in SAMESITE_VALIDOS:
        errores.append(f"AUTH_COOKIE_SAMESITE debe ser uno de: {', '.join(SAMESITE_VALIDOS)}.")
    elif auth_cookie_enabled and auth_cookie_samesite == 'None' and not auth_cookie_secure:
        errores.append('AUTH_COOKIE_SAMESITE=None exige AUTH_COOKIE_SECURE=True (los navegadores la rechazan).')

    if num_proxies is not None and num_proxies < 0:
        errores.append('NUM_PROXIES no puede ser negativo.')

    if not debug:
        # Bloque 8: la contraseña de la BD no puede faltar ni ser la de ejemplo.
        if db_password is not None and (not db_password.strip() or db_password in DB_PASSWORDS_INSEGURAS):
            errores.append('DB_PASSWORD es obligatoria en producción y no puede ser un valor de ejemplo.')
        # Detrás de Nginx (cabecera X-Forwarded-Proto) todas las peticiones llegan desde el proxy:
        # sin NUM_PROXIES=1 el throttling del login trataría a todos los usuarios como una sola IP.
        if proxy_ssl_header and num_proxies == 0:
            errores.append('Con SECURE_PROXY_SSL_HEADER_HTTPS=True define NUM_PROXIES=1 (Nginx delante de Gunicorn).')
        if token_max_age > TOKEN_MAX_AGE_PRODUCCION_MAXIMO:
            errores.append('TOKEN_MAX_AGE_SECONDS no puede superar 30 días en producción (recomendado: 8–12 horas).')
        origenes = [o.strip() for o in cors_origins if o and o.strip()]
        if any(o in ('*', 'null') for o in origenes):
            errores.append("CORS_ALLOWED_ORIGINS no puede contener '*' ni 'null'. Lista los orígenes reales.")
        if not sin_https:
            if not session_cookie_secure or not csrf_cookie_secure:
                errores.append(
                    'SESSION_COOKIE_SECURE y CSRF_COOKIE_SECURE deben ser True en producción '
                    '(o declara PRODUCCION_SIN_HTTPS=True si el servidor no tiene HTTPS).'
                )
            if auth_cookie_enabled and not auth_cookie_secure:
                errores.append('AUTH_COOKIE_SECURE debe ser True en producción con HTTPS.')
            inseguros = [o for o in [*origenes, *csrf_trusted_origins]
                         if o and o.strip().startswith('http://') and not _es_origen_local(o.strip())]
            if inseguros:
                errores.append(
                    'Orígenes http:// no locales en CORS_ALLOWED_ORIGINS/CSRF_TRUSTED_ORIGINS: '
                    f"{', '.join(sorted(set(inseguros)))}. Usa https:// (o PRODUCCION_SIN_HTTPS=True)."
                )
    if errores:
        raise ImproperlyConfigured('Configuración insegura: ' + ' | '.join(errores))
