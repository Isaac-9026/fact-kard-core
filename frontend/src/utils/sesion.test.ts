/// <reference types="node" />

import assert from 'node:assert/strict';
import test from 'node:test';
import {
  crearControlCierreSesion,
  debeCerrarSesionPor401,
  esSolicitudDeLogin,
  resolverAccesoRuta,
  tokenDesdeAuthorization,
} from './sesion.ts';

// --- Acceso a rutas privadas (/kardex y demás) -------------------------------

test('usuario autenticado y verificado accede a la ruta privada', () => {
  assert.equal(resolverAccesoRuta({ token: 'tk', verificandoSesion: false }), 'permitido');
});

test('sin sesión (o tras logout) el acceso directo a /kardex redirige a /login', () => {
  assert.equal(resolverAccesoRuta({ token: null, verificandoSesion: false }), 'redirigir_login');
  // Aunque quede una verificación pendiente, sin token nunca se muestra contenido privado.
  assert.equal(resolverAccesoRuta({ token: null, verificandoSesion: true }), 'redirigir_login');
});

test('con token guardado sin validar no se renderiza el módulo privado', () => {
  assert.equal(resolverAccesoRuta({ token: 'tk-guardado', verificandoSesion: true }), 'verificando');
});

// --- Interceptor 401 -------------------------------------------------------

test('token inválido: un 401 con el token vigente cierra la sesión', () => {
  assert.equal(
    debeCerrarSesionPor401({ status: 401, url: '/kardex/movimientos/', tokenEnviado: 'tk', tokenActual: 'tk' }),
    true,
  );
});

test('el 401 del propio login (credenciales erradas) no dispara cierre de sesión', () => {
  for (const url of ['/usuarios/login/', '/usuarios/login', 'http://localhost:8000/api/usuarios/login/?x=1']) {
    assert.equal(esSolicitudDeLogin(url), true, url);
    assert.equal(
      debeCerrarSesionPor401({ status: 401, url, tokenEnviado: 'tk', tokenActual: 'tk' }),
      false,
      url,
    );
  }
});

test('un 401 tardío de un token anterior no cierra la sesión nueva', () => {
  assert.equal(
    debeCerrarSesionPor401({ status: 401, url: '/usuarios/me/', tokenEnviado: 'viejo', tokenActual: 'nuevo' }),
    false,
  );
});

test('un 401 sin token enviado o tras logout no hace nada', () => {
  assert.equal(
    debeCerrarSesionPor401({ status: 401, url: '/usuarios/me/', tokenEnviado: null, tokenActual: null }),
    false,
  );
  assert.equal(
    debeCerrarSesionPor401({ status: 401, url: '/usuarios/me/', tokenEnviado: 'tk', tokenActual: null }),
    false,
  );
});

test('403, 400 y 500 no cierran la sesión', () => {
  for (const status of [400, 403, 404, 500]) {
    assert.equal(
      debeCerrarSesionPor401({ status, url: '/kardex/movimientos/', tokenEnviado: 'tk', tokenActual: 'tk' }),
      false,
      String(status),
    );
  }
});

test('extrae el token del header Authorization', () => {
  assert.equal(tokenDesdeAuthorization('Bearer abc.def'), 'abc.def');
  assert.equal(tokenDesdeAuthorization('Token abc'), 'abc');
  assert.equal(tokenDesdeAuthorization('Basic abc'), null);
  assert.equal(tokenDesdeAuthorization(undefined), null);
});

// --- Varios 401 simultáneos -----------------------------------------------

test('varios 401 simultáneos ejecutan un solo logout hasta el siguiente login', () => {
  const control = crearControlCierreSesion();
  let logouts = 0;
  const logout = () => { logouts += 1; };

  assert.equal(control.intentar(logout), true);
  assert.equal(control.intentar(logout), false);
  assert.equal(control.intentar(logout), false);
  assert.equal(logouts, 1);

  control.reiniciar(); // nuevo login
  assert.equal(control.intentar(logout), true);
  assert.equal(logouts, 2);
});
