/// <reference types="node" />

import assert from 'node:assert/strict'
import test from 'node:test'
import {
  calcularContrastRatio,
  esHexValido,
  generarThemingSidebar,
  hexToRgb,
  obtenerFiltroLogo,
  obtenerInicialesEmpresa,
  resolverUrlMedia,
  TEXTO_CLARO_SIDEBAR,
} from './identidadEmpresa.ts'

test('obtenerInicialesEmpresa extrae iniciales limpias ignorando palabras societarias comunes', () => {
  assert.equal(obtenerInicialesEmpresa('FERRETERIA CENTRAL S.A.C.'), 'FC')
  assert.equal(obtenerInicialesEmpresa('DISTRIBUIDORA DE ALIMENTOS DEL SUR S.R.L.'), 'DA')
  assert.equal(obtenerInicialesEmpresa('IMPORTACIONES Y EXPORTACIONES EIRL'), 'IE')
  assert.equal(obtenerInicialesEmpresa('GOOGLE'), 'GO')
  assert.equal(obtenerInicialesEmpresa('A S.A.'), 'AS')
  assert.equal(obtenerInicialesEmpresa(''), 'FK')
  assert.equal(obtenerInicialesEmpresa('  '), 'FK')
})

test('esHexValido valida formato estricto #RRGGBB', () => {
  assert.equal(esHexValido('#4F46E5'), true)
  assert.equal(esHexValido('#ffffff'), true)
  assert.equal(esHexValido('#000000'), true)
  assert.equal(esHexValido('#10B981'), true)

  assert.equal(esHexValido('4F46E5'), false)
  assert.equal(esHexValido('#FFF'), false)
  assert.equal(esHexValido('#GGGGGG'), false)
  assert.equal(esHexValido('#1234567'), false)
  assert.equal(esHexValido(''), false)
})

test('generarThemingSidebar devuelve null para colores ausentes o inválidos', () => {
  assert.equal(generarThemingSidebar(null), null)
  assert.equal(generarThemingSidebar(undefined), null)
  assert.equal(generarThemingSidebar('invalido'), null)
})

test('generarThemingSidebar garantiza ratio WCAG >= 7.0:1 para el fondo con colores estándar y extremos', () => {
  const rgbTexto = hexToRgb(TEXTO_CLARO_SIDEBAR)
  const coloresPrueba = [
    '#4F46E5', // Índigo original
    '#2563EB', // Azul
    '#10B981', // Esmeralda
    '#FFFF00', // Amarillo brillante extremo
    '#FFFFFF', // Blanco extremo
    '#000000', // Negro
    '#F43F5E', // Rosa intenso
    '#F97316', // Naranja brillante
    '#06B6D4', // Cian claro
  ]

  for (const color of coloresPrueba) {
    const theming = generarThemingSidebar(color)
    assert.ok(theming, `Theming debe generarse para ${color}`)

    const rgbFondo = hexToRgb(theming['--tenant-sidebar-bg'])
    const ratioFondo = calcularContrastRatio(rgbTexto, rgbFondo)
    assert.ok(
      ratioFondo >= 7.0,
      `Fondo para color ${color} (${theming['--tenant-sidebar-bg']}) ratio=${ratioFondo.toFixed(2)} debe ser >= 7.0`
    )

    const rgbSuperficie = hexToRgb(theming['--tenant-sidebar-surface'])
    const ratioSuperficie = calcularContrastRatio(rgbTexto, rgbSuperficie)
    assert.ok(
      ratioSuperficie >= 4.5,
      `Superficie para color ${color} (${theming['--tenant-sidebar-surface']}) ratio=${ratioSuperficie.toFixed(2)} debe ser >= 4.5`
    )
    assert.ok(theming['--tenant-sidebar-mesh-bg'].includes('radial-gradient'))
  }
})


test('resolverUrlMedia maneja blobs, urls absolutas y rutas relativas con backend host', () => {
  assert.equal(resolverUrlMedia(null), null)
  assert.equal(resolverUrlMedia(''), null)
  assert.equal(resolverUrlMedia('   '), null)

  assert.equal(resolverUrlMedia('blob:http://localhost:5173/preview-123'), 'blob:http://localhost:5173/preview-123')
  assert.equal(resolverUrlMedia('data:image/webp;base64,xxxx'), 'data:image/webp;base64,xxxx')
  assert.equal(resolverUrlMedia('https://cdn.example.com/logo.webp'), 'https://cdn.example.com/logo.webp')
  assert.equal(resolverUrlMedia('http://localhost:8000/media/logos/1.webp'), 'http://localhost:8000/media/logos/1.webp')

  // Ruta relativa desde la BD debe prefijar el host del backend
  const res = resolverUrlMedia('/media/empresas/1/logos/test.webp')
  assert.ok(res?.endsWith('/media/empresas/1/logos/test.webp'))
  assert.ok(res?.startsWith('http://') || res?.startsWith('https://'))
})

test('obtenerFiltroLogo genera halo perimetral blanco sobre temas oscuros y sombra sutil sobre blanco', () => {
  const filtroConTema = obtenerFiltroLogo(true)
  assert.ok(filtroConTema.includes('rgba(255, 255, 255'))
  assert.ok(filtroConTema.includes('drop-shadow'))

  const filtroBlanco = obtenerFiltroLogo(false)
  assert.ok(filtroBlanco.includes('rgba(15, 23, 42'))
  assert.ok(filtroBlanco.includes('drop-shadow'))
})
