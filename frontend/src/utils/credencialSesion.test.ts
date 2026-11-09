import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  SESION_COOKIE, borrarCredencial, encabezadoAutorizacion, esSesionCookie, guardarCredencial, leerCookie,
  leerCredencial, requiereCsrf,
} from './credencialSesion.ts';
import { debeCerrarSesionPor401 } from './sesion.ts';

const almacen = () => {
  const datos = new Map<string, string>();
  return {
    datos,
    getItem: (k: string) => datos.get(k) ?? null,
    setItem: (k: string, v: string) => { datos.set(k, v); },
    removeItem: (k: string) => { datos.delete(k); },
  };
};

test('modo token (actual): se guarda el token y viaja en Authorization', () => {
  const a = almacen();
  assert.equal(guardarCredencial(a, 'tk-123'), 'tk-123');
  assert.equal(leerCredencial(a), 'tk-123');
  assert.equal(encabezadoAutorizacion(leerCredencial(a)), 'Bearer tk-123');
  assert.equal(a.datos.has('sesion_cookie'), false);
});

test('modo cookie HttpOnly: no se guarda ningún token, solo la marca', () => {
  const a = almacen();
  guardarCredencial(a, 'tk-viejo');
  assert.equal(guardarCredencial(a, undefined), SESION_COOKIE);  // login sin token en la respuesta
  assert.deepEqual([...a.datos.entries()], [['sesion_cookie', '1']]);
  assert.equal(leerCredencial(a), SESION_COOKIE);
  assert.equal(esSesionCookie(leerCredencial(a)), true);
  assert.equal(encabezadoAutorizacion(SESION_COOKIE), null);
});

test('logout borra cualquiera de los dos modos', () => {
  const a = almacen();
  guardarCredencial(a, null);
  borrarCredencial(a);
  assert.equal(leerCredencial(a), null);
  assert.equal(a.datos.size, 0);
});

test('un 401 cierra la sesión también en modo cookie', () => {
  assert.equal(debeCerrarSesionPor401({ status: 401, url: '/kardex/', tokenEnviado: SESION_COOKIE, tokenActual: SESION_COOKIE }), true);
  // Respuesta tardía de una sesión anterior (token) no cierra la sesión cookie nueva.
  assert.equal(debeCerrarSesionPor401({ status: 401, url: '/kardex/', tokenEnviado: 'tk-viejo', tokenActual: SESION_COOKIE }), false);
  assert.equal(debeCerrarSesionPor401({ status: 401, url: '/usuarios/login/', tokenEnviado: SESION_COOKIE, tokenActual: SESION_COOKIE }), false);
});

test('CSRF solo en métodos que escriben; lectura de la cookie csrftoken', () => {
  assert.deepEqual(['GET', 'head', undefined, 'POST', 'patch', 'DELETE'].map(requiereCsrf), [false, false, false, true, true, true]);
  assert.equal(leerCookie('a=1; csrftoken=abc%3D; b=2', 'csrftoken'), 'abc=');
  assert.equal(leerCookie('a=1', 'csrftoken'), null);
});
