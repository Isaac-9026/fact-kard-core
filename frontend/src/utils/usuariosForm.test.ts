/// <reference types="node" />

import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import {
  validarFormularioUsuario,
  validarCambioClave,
  validarReseteoClave,
  filtrarUsuarios,
  construirPayloadAsignaciones,
} from './usuariosForm.ts';
import type { UsuarioEstudio } from '../api/usuarios.ts';

const appCode = readFileSync(new URL('../App.tsx', import.meta.url), 'utf8');
const layoutCode = readFileSync(new URL('../layouts/MainLayout.tsx', import.meta.url), 'utf8');

test('validarFormularioUsuario exige username, email valido y password >= 8 al crear', () => {
  const sinUsername = validarFormularioUsuario({
    username: '',
    email: 'user@test.pe',
    passwordInicial: 'Password123',
    esEdicion: false,
  });
  assert.equal(sinUsername.valido, false);
  assert.match(sinUsername.error || '', /nombre de usuario es obligatorio/);

  const emailInvalido = validarFormularioUsuario({
    username: 'jperez',
    email: 'correo_sin_arroba',
    passwordInicial: 'Password123',
    esEdicion: false,
  });
  assert.equal(emailInvalido.valido, false);
  assert.match(emailInvalido.error || '', /correo electrónico válido/);

  const passwordCorto = validarFormularioUsuario({
    username: 'jperez',
    email: 'jperez@test.pe',
    passwordInicial: '12345',
    esEdicion: false,
  });
  assert.equal(passwordCorto.valido, false);
  assert.match(passwordCorto.error || '', /al menos 8 caracteres/);

  const valido = validarFormularioUsuario({
    username: 'jperez',
    email: 'jperez@test.pe',
    passwordInicial: 'ClaveSegura2026!',
    esEdicion: false,
  });
  assert.equal(valido.valido, true);
  assert.equal(valido.error, undefined);
});

test('validarFormularioUsuario prohíbe desactivar la propia cuenta en sesión (candado de seguridad)', () => {
  const propioDesactivado = validarFormularioUsuario({
    username: 'admin',
    email: 'admin@estudio.pe',
    activo: false,
    esEdicion: true,
    usuarioSesionId: 42,
    editandoUsuarioId: 42,
  });
  assert.equal(propioDesactivado.valido, false);
  assert.match(propioDesactivado.error || '', /No puedes desactivar tu propia cuenta en sesión/);

  const otroDesactivado = validarFormularioUsuario({
    username: 'operador',
    email: 'operador@estudio.pe',
    activo: false,
    esEdicion: true,
    usuarioSesionId: 42,
    editandoUsuarioId: 99,
  });
  assert.equal(otroDesactivado.valido, true);
});

test('validarCambioClave verifica coincidencia, longitud y diferencia respecto a la actual', () => {
  const sinActual = validarCambioClave({
    claveActual: '',
    claveNueva: 'NuevaClave123',
    claveConfirmar: 'NuevaClave123',
  });
  assert.equal(sinActual.valido, false);

  const corta = validarCambioClave({
    claveActual: 'ActualClave123',
    claveNueva: '12345',
    claveConfirmar: '12345',
  });
  assert.equal(corta.valido, false);

  const noCoincide = validarCambioClave({
    claveActual: 'ActualClave123',
    claveNueva: 'NuevaClave123',
    claveConfirmar: 'OtraClaveDiferente',
  });
  assert.equal(noCoincide.valido, false);
  assert.match(noCoincide.error || '', /no coinciden/);

  const mismaClave = validarCambioClave({
    claveActual: 'MismaClave123',
    claveNueva: 'MismaClave123',
    claveConfirmar: 'MismaClave123',
  });
  assert.equal(mismaClave.valido, false);
  assert.match(mismaClave.error || '', /diferente de la actual/);

  const correcto = validarCambioClave({
    claveActual: 'ClaveAnterior2026!',
    claveNueva: 'ClaveSuperNueva2026!',
    claveConfirmar: 'ClaveSuperNueva2026!',
  });
  assert.equal(correcto.valido, true);
});

test('validarReseteoClave exige al menos 8 caracteres', () => {
  assert.equal(validarReseteoClave('12345').valido, false);
  assert.equal(validarReseteoClave('ClaveTemporal2026').valido, true);
});

test('filtrarUsuarios filtra correctamente por texto y estado', () => {
  const lista: UsuarioEstudio[] = [
    {
      id: 1,
      username: 'admin',
      email: 'admin@estudio.pe',
      activo: true,
      is_active: true,
      es_admin_global: true,
      is_staff: true,
      asignaciones: [
        { id: 1, empresa_id: 10, empresa_ruc: '20100070970', empresa_razon_social: 'EMPRESA ALFA', rol: 'ADMIN', activo: true },
      ],
    },
    {
      id: 2,
      username: 'asistente',
      email: 'asistente@estudio.pe',
      activo: false,
      is_active: false,
      es_admin_global: false,
      is_staff: false,
      asignaciones: [
        { id: 2, empresa_id: 20, empresa_ruc: '20601234567', empresa_razon_social: 'EMPRESA BETA', rol: 'USUARIO', activo: true },
      ],
    },
  ];

  const soloActivos = filtrarUsuarios(lista, '', 'ACTIVOS');
  assert.equal(soloActivos.length, 1);
  assert.equal(soloActivos[0].username, 'admin');

  const soloInactivos = filtrarUsuarios(lista, '', 'INACTIVOS');
  assert.equal(soloInactivos.length, 1);
  assert.equal(soloInactivos[0].username, 'asistente');

  const porRuc = filtrarUsuarios(lista, '20601234567', 'TODOS');
  assert.equal(porRuc.length, 1);
  assert.equal(porRuc[0].username, 'asistente');
});

test('construirPayloadAsignaciones convierte la matriz de checkboxes en array', () => {
  const payload = construirPayloadAsignaciones({
    10: { asignado: true, rol: 'ADMIN' },
    20: { asignado: false, rol: 'USUARIO' },
  });
  assert.deepEqual(payload, [
    { empresa_id: 10, rol: 'ADMIN', activo: true },
    { empresa_id: 20, rol: 'USUARIO', activo: false },
  ]);
});

test('la ruta /usuarios está registrada en App.tsx y el trigger de cambio de contraseña en MainLayout.tsx', () => {
  assert.match(appCode, /path="usuarios"/);
  assert.match(layoutCode, /Cambiar Contraseña/);
  assert.match(layoutCode, /KeyRound/);
});

