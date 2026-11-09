#!/usr/bin/env python3
"""
FACT-KARD — smoke test NO destructivo (solo lecturas + login/logout).

No crea, confirma ni anula documentos: recorre las pantallas principales con GET y
termina cerrando la sesión. Solo usa la librería estándar de Python.

Uso (en el VPS o desde cualquier equipo):
    FK_SMOKE_USER=usuario_qa python3 deploy/scripts/smoke_test.py --base https://sistema.asescon.net --frontend
    (la contraseña se pide por teclado; también puede venir en FK_SMOKE_PASSWORD)

Contra Gunicorn directo (sin Nginx), dentro del VPS:
    python3 deploy/scripts/smoke_test.py --base http://127.0.0.1:8001 --host sistema.asescon.net

Código de salida: 0 si todo pasó, 1 si algo falló. Nunca imprime la contraseña ni el token.
"""
import argparse
import http.cookiejar
import getpass
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


class Cliente:
    def __init__(self, base, host=None, inseguro=False):
        self.base = base.rstrip('/')
        self.host = host
        self.token = None
        self.empresa_id = None
        self.contexto = ssl._create_unverified_context() if inseguro else None  # noqa: S323 — solo pruebas locales
        # Bloque 9: con AUTH_COOKIE_ENABLED=True la sesión viaja en la cookie HttpOnly.
        self.cookies = http.cookiejar.CookieJar()
        self.abridor = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=self.contexto), urllib.request.HTTPCookieProcessor(self.cookies),
        )
        self.modo_cookie = False

    def cookie(self, nombre):
        return next((c.value for c in self.cookies if c.name == nombre), None)

    def pedir(self, metodo, ruta, datos=None, params=None, crudo=False):
        url = self.base + ruta
        if params:
            url += '?' + urllib.parse.urlencode(params)
        cuerpo = json.dumps(datos).encode() if datos is not None else None
        req = urllib.request.Request(url, data=cuerpo, method=metodo)
        req.add_header('Accept', 'application/json')
        if cuerpo is not None:
            req.add_header('Content-Type', 'application/json')
        if self.host:
            req.add_header('Host', self.host)
        if self.token:
            req.add_header('Authorization', f'Bearer {self.token}')
        if self.modo_cookie and metodo not in ('GET', 'HEAD', 'OPTIONS') and self.cookie('csrftoken'):
            req.add_header('X-CSRFToken', self.cookie('csrftoken'))
            req.add_header('Referer', self.base + '/')
        if self.empresa_id:
            req.add_header('X-Empresa-Id', str(self.empresa_id))
        inicio = time.monotonic()
        try:
            with self.abridor.open(req, timeout=60) as resp:
                contenido = resp.read()
                estado = resp.status
        except urllib.error.HTTPError as err:
            contenido = err.read()
            estado = err.code
        ms = int((time.monotonic() - inicio) * 1000)
        if crudo:
            return estado, contenido.decode('utf-8', 'replace'), ms
        try:
            return estado, json.loads(contenido or b'null'), ms
        except ValueError:
            return estado, None, ms


class Resultado:
    def __init__(self):
        self.fallos = 0

    def ok(self, nombre, cond, estado, ms, detalle=''):
        marca = 'OK  ' if cond else 'FALLO'
        if not cond:
            self.fallos += 1
        print(f'[{marca}] {nombre:<34} HTTP {estado:<4} {ms:>5} ms  {detalle}')

    def aviso(self, nombre, detalle):
        print(f'[AVISO] {nombre:<33} {detalle}')


def contar(data):
    if isinstance(data, dict) and 'count' in data:
        return data['count']
    if isinstance(data, list):
        return len(data)
    return '?'


def main():
    ap = argparse.ArgumentParser(description='Smoke test no destructivo de FACT-KARD')
    ap.add_argument('--base', default=os.environ.get('FK_SMOKE_BASE', 'http://127.0.0.1:8001'),
                    help='URL base (https://sistema.asescon.net o http://127.0.0.1:8001)')
    ap.add_argument('--usuario', default=os.environ.get('FK_SMOKE_USER'))
    ap.add_argument('--empresa', type=int, help='ID de empresa (por defecto la primera del usuario)')
    ap.add_argument('--host', help='Cabecera Host (al probar Gunicorn directo)')
    ap.add_argument('--frontend', action='store_true', help='Verificar también que / sirva el frontend')
    ap.add_argument('--inseguro', action='store_true', help='Aceptar certificados autofirmados (solo pruebas locales)')
    args = ap.parse_args()

    c = Cliente(args.base, host=args.host, inseguro=args.inseguro)
    r = Resultado()
    print(f'FACT-KARD smoke test → {c.base}\n')

    estado, data, ms = c.pedir('GET', '/api/health/')
    r.ok('Health check', estado == 200 and (data or {}).get('status') == 'ok', estado, ms, json.dumps(data))

    if args.frontend:
        estado, html, ms = c.pedir('GET', '/', crudo=True)
        r.ok('Frontend (/)', estado == 200 and 'id="root"' in html, estado, ms)
        estado, html, ms = c.pedir('GET', '/dashboard', crudo=True)
        r.ok('Frontend ruta SPA (/dashboard)', estado == 200 and 'id="root"' in html, estado, ms)

    if not args.usuario:
        print('\nSin --usuario (o FK_SMOKE_USER): solo se verificó el health check.')
        return 1 if r.fallos else 0
    clave = os.environ.get('FK_SMOKE_PASSWORD') or getpass.getpass(f'Contraseña de {args.usuario}: ')

    estado, data, ms = c.pedir('POST', '/api/usuarios/login/', {'username': args.usuario, 'password': clave})
    del clave
    c.token = (data or {}).get('token')
    c.modo_cookie = estado == 200 and not c.token and c.cookie('fk_sesion') is not None
    r.ok('Login', estado == 200 and (bool(c.token) or c.modo_cookie), estado, ms,
         'sesión por cookie HttpOnly' if c.modo_cookie else 'sesión por token')
    if estado != 200 or not (c.token or c.modo_cookie):
        print('\nNo se pudo iniciar sesión; se detiene la prueba.')
        return 1
    empresas = data.get('empresas') or []
    try:
        c.empresa_id = args.empresa or (empresas[0]['id'] if empresas else None)
        r.ok('Empresa activa', c.empresa_id is not None, '-', 0, f'id={c.empresa_id} ({len(empresas)} asignadas)')
        if c.empresa_id is None:
            return 1

        estado, data, ms = c.pedir('GET', '/api/usuarios/me/')
        r.ok('Sesión (/me)', estado == 200, estado, ms)
        estado, data, ms = c.pedir('GET', '/api/empresas/')
        r.ok('Empresas', estado == 200, estado, ms, f'{contar(data)} empresas')
        estado, periodos, ms = c.pedir('GET', '/api/empresas/periodos/')
        r.ok('Períodos', estado == 200, estado, ms, f'{contar(periodos)} períodos')
        periodo = next((p for p in (periodos or []) if p.get('estado') == 'ABIERTO'), (periodos or [None])[0])

        # Dashboard: las mismas consultas que hace la pantalla.
        estado, data, ms = c.pedir('GET', '/api/reportes/kardex/', params={'page': 1, 'page_size': 1})
        resumen = (data or {}).get('resumen') or {}
        r.ok('Dashboard · stock y valor', estado == 200 and 'saldo_final_valor' in resumen, estado, ms,
             f"valor={resumen.get('saldo_final_valor')}")
        estado, data, ms = c.pedir('GET', '/api/kardex/incidencias/', params={'page': 1, 'page_size': 1})
        r.ok('Dashboard · incidencias', estado == 200, estado, ms, f'{contar(data)} incidencias')
        estado, data, ms = c.pedir('GET', '/api/empresas/cierres/')
        r.ok('Dashboard · cierres', estado == 200, estado, ms, f'{contar(data)} cierres')

        estado, data, ms = c.pedir('GET', '/api/kardex/saldos-actuales/')
        r.ok('Inventario (saldos actuales)', estado == 200 and 'saldos_cpp' in (data or {}), estado, ms,
             f"{len((data or {}).get('saldos_cpp', []))} productos")
        estado, data, ms = c.pedir('GET', '/api/documentos/', params={'page': 1, 'page_size': 5})
        r.ok('Documentos (página 1)', estado == 200 and 'results' in (data or {}), estado, ms, f'{contar(data)} documentos')
        estado, data, ms = c.pedir('GET', '/api/documentos/', params={'page': 1, 'page_size': 1, 'es_nota': 'true'})
        r.ok('Notas de crédito/débito', estado == 200, estado, ms, f'{contar(data)} notas')

        params_kardex = {'page': 1, 'page_size': 20}
        if periodo:
            params_kardex['periodo_id'] = periodo['id']
        estado, data, ms = c.pedir('GET', '/api/reportes/kardex/', params=params_kardex)
        r.ok('Kardex valorizado', estado == 200 and 'movimientos' in (data or {}), estado, ms,
             f"{((data or {}).get('paginacion') or {}).get('count', '?')} movimientos")

        if periodo:
            estado, data, ms = c.pedir('GET', '/api/reportes/formato-13-1/', params={'periodo_id': periodo['id']})
            r.ok('Formato 13.1', estado == 200 and 'reportes' in (data or {}), estado, ms,
                 f"período {periodo.get('anio')}-{str(periodo.get('mes')).zfill(2)}, {len((data or {}).get('reportes', []))} reportes")
        else:
            r.aviso('Formato 13.1', 'sin períodos: no se probó')

        estado, data, ms = c.pedir('GET', '/api/auditoria/', params={'page': 1, 'page_size': 5})
        r.ok('Auditoría', estado == 200, estado, ms, f'{contar(data)} registros')
    finally:
        estado, _, ms = c.pedir('POST', '/api/usuarios/logout/')
        r.ok('Logout', estado == 204, estado, ms)
        estado, _, ms = c.pedir('GET', '/api/usuarios/me/')
        r.ok('Token revocado tras logout', estado == 401, estado, ms)
        c.token = None
        if c.modo_cookie:
            r.ok('Cookie de sesión borrada', not c.cookie('fk_sesion'), '-', 0)

    print(f"\n{'TODO OK' if not r.fallos else f'{r.fallos} FALLO(S)'}")
    return 1 if r.fallos else 0


if __name__ == '__main__':
    sys.exit(main())
