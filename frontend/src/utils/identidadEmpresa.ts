/**
 * Motor de Identidad Visual Multiempresa y Accesibilidad WCAG 2.1
 * FACT-KARD ERP Contable B2B
 */

export interface TokensTemaSidebar {
  '--tenant-sidebar-bg': string
  '--tenant-sidebar-surface': string
  '--tenant-sidebar-border': string
  '--tenant-sidebar-accent': string
  '--tenant-sidebar-text': string
  '--tenant-sidebar-text-muted': string
  '--tenant-sidebar-mesh-bg': string
}

export const TEXTO_CLARO_SIDEBAR = '#F8FAFC' // Slate 50

// Paletas ejecutivas predefinidas para 1-click theming
export const PALETAS_EJECUTIVAS = [
  { nombre: 'Índigo Corporativo', hex: '#4F46E5' },
  { nombre: 'Azul Marino', hex: '#2563EB' },
  { nombre: 'Esmeralda Contable', hex: '#059669' },
  { nombre: 'Teal Fiscal', hex: '#0D9488' },
  { nombre: 'Cian Nórdico', hex: '#0284C7' },
  { nombre: 'Púrpura Ejecutivo', hex: '#7C3AED' },
  { nombre: 'Borgoña / Vino', hex: '#9F1239' },
  { nombre: 'Ámbar / Bronce', hex: '#D97706' },
  { nombre: 'Pizarra Neutro', hex: '#475569' },
] as const

const PALABRAS_A_IGNORAR = new Set([
  'DE', 'DEL', 'LA', 'LAS', 'EL', 'LOS', 'Y', 'E', 'EN', 'POR', 'PARA',
  'SA', 'SAC', 'EIRL', 'SRL', 'SAA', 'SACS', 'LTDA', 'CIA',
  'SOCIEDAD', 'ANONIMA', 'CERRADA', 'ABIERTA', 'COMERCIAL', 'RESPONSABILIDAD', 'LIMITADA',
])

/**
 * Extrae hasta 2 iniciales limpias de la Razón Social.
 */
export function obtenerInicialesEmpresa(razonSocial: string): string {
  if (!razonSocial || typeof razonSocial !== 'string') return 'FK'

  const palabrasLimpias = razonSocial
    .toUpperCase()
    .replace(/[.,/#!$%^&*;:{}=\-_`~()]/g, ' ')
    .split(/\s+/)
    .filter((palabra) => palabra.length > 0 && !PALABRAS_A_IGNORAR.has(palabra))

  if (palabrasLimpias.length === 0) {
    const fallback = razonSocial.trim().replace(/[^a-zA-Z0-9]/g, '').toUpperCase()
    return fallback.slice(0, 2) || 'FK'
  }

  if (palabrasLimpias.length === 1) {
    const unica = palabrasLimpias[0]
    return unica.length >= 2 ? unica.slice(0, 2) : unica + 'K'
  }

  return (palabrasLimpias[0][0] + palabrasLimpias[1][0]).toUpperCase()
}

/**
 * Resuelve la URL pública para mostrar un archivo multimedia (ej. logo).
 * Maneja blobs en memoria (previews temporales), URLs absolutas y rutas relativas al backend (/media/...).
 */
export function resolverUrlMedia(url: string | null | undefined): string | null {
  if (!url || typeof url !== 'string') return null
  const limpio = url.trim()
  if (!limpio) return null
  if (
    limpio.startsWith('blob:') ||
    limpio.startsWith('data:') ||
    limpio.startsWith('http://') ||
    limpio.startsWith('https://')
  ) {
    return limpio
  }
  // Tipado por vite/client; `?.` porque en las pruebas de Node (sin Vite) import.meta.env no existe.
  const apiBase = import.meta.env?.VITE_API_URL || 'http://localhost:8000/api'
  const hostBase = apiBase.replace(/\/api\/?$/, '')
  const ruta = limpio.startsWith('/') ? limpio : `/${limpio}`
  return `${hostBase}${ruta}`
}

/**
 * Valida si un string es un color hexadecimal estricto #RRGGBB.
 */
export function esHexValido(hex: string): boolean {
  return /^#[0-9A-Fa-f]{6}$/.test((hex || '').trim())
}

/**
 * Retorna el filtro CSS adaptativo para logotipos transparentes (PNG/SVG/WebP).
 * - Con tema/gradiente: Aplica un halo perimetral sutil que despega letras o isotipos oscuros sin añadir cajas.
 * - Sin tema (blanco): Aplica una sombra suave ambiental para dar presencia sobre blanco.
 */
export function obtenerFiltroLogo(tieneTema: boolean): string {
  return tieneTema
    ? 'drop-shadow(0 1px 2px rgba(255, 255, 255, 0.45)) drop-shadow(0 0 1px rgba(255, 255, 255, 0.65))'
    : 'drop-shadow(0 1px 2px rgba(15, 23, 42, 0.08))'
}

export function hexToRgb(hex: string): { r: number; g: number; b: number } {
  const normalizado = hex.replace('#', '').trim()
  const num = parseInt(normalizado, 16)
  return {
    r: (num >> 16) & 255,
    g: (num >> 8) & 255,
    b: num & 255,
  }
}

export function rgbToHex(r: number, g: number, b: number): string {
  const clamp = (v: number) => Math.max(0, Math.min(255, Math.round(v)))
  const toHex = (v: number) => clamp(v).toString(16).padStart(2, '0')
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`.toUpperCase()
}

export function rgbToHsl(r: number, g: number, b: number): { h: number; s: number; l: number } {
  const rNorm = r / 255
  const gNorm = g / 255
  const bNorm = b / 255
  const max = Math.max(rNorm, gNorm, bNorm)
  const min = Math.min(rNorm, gNorm, bNorm)
  let h = 0
  let s = 0
  const l = (max + min) / 2

  if (max !== min) {
    const d = max - min
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min)
    switch (max) {
      case rNorm:
        h = (gNorm - bNorm) / d + (gNorm < bNorm ? 6 : 0)
        break
      case gNorm:
        h = (bNorm - rNorm) / d + 2
        break
      case bNorm:
        h = (rNorm - gNorm) / d + 4
        break
    }
    h *= 60
  }

  return { h, s, l }
}

export function hslToRgb(h: number, s: number, l: number): { r: number; g: number; b: number } {
  const hNorm = ((h % 360) + 360) % 360
  const c = (1 - Math.abs(2 * l - 1)) * s
  const x = c * (1 - Math.abs(((hNorm / 60) % 2) - 1))
  const m = l - c / 2

  // Sector de 60° del matiz → (R', G', B') de la conversión HSL estándar.
  const [rPrime, gPrime, bPrime] =
    hNorm < 60 ? [c, x, 0]
      : hNorm < 120 ? [x, c, 0]
        : hNorm < 180 ? [0, c, x]
          : hNorm < 240 ? [0, x, c]
            : hNorm < 300 ? [x, 0, c]
              : [c, 0, x]

  return {
    r: Math.round((rPrime + m) * 255),
    g: Math.round((gPrime + m) * 255),
    b: Math.round((bPrime + m) * 255),
  }
}

/**
 * Calcula la luminancia relativa según la especificación W3C WCAG 2.1.
 */
export function calcularLuminanciaRelativa(r: number, g: number, b: number): number {
  const sRGB = [r / 255, g / 255, b / 255].map((val) =>
    val <= 0.04045 ? val / 12.92 : Math.pow((val + 0.055) / 1.055, 2.4)
  )
  return 0.2126 * sRGB[0] + 0.7152 * sRGB[1] + 0.0722 * sRGB[2]
}

/**
 * Calcula el ratio de contraste entre dos colores RGB (1:1 a 21:1).
 */
export function calcularContrastRatio(
  rgb1: { r: number; g: number; b: number },
  rgb2: { r: number; g: number; b: number }
): number {
  const l1 = calcularLuminanciaRelativa(rgb1.r, rgb1.g, rgb1.b)
  const l2 = calcularLuminanciaRelativa(rgb2.r, rgb2.g, rgb2.b)
  const masClaro = Math.max(l1, l2)
  const masOscuro = Math.min(l1, l2)
  return (masClaro + 0.05) / (masOscuro + 0.05)
}

/**
 * Genera el theming dinámico para el Sidebar garantizando WCAG 2.1 AAA/AA.
 */
export function generarThemingSidebar(colorTema?: string | null): TokensTemaSidebar | null {
  if (!colorTema || !esHexValido(colorTema)) {
    return null
  }

  const rgbOriginal = hexToRgb(colorTema)
  const hsl = rgbToHsl(rgbOriginal.r, rgbOriginal.g, rgbOriginal.b)
  const rgbTextoClaro = hexToRgb(TEXTO_CLARO_SIDEBAR)

  // 1. Fondo del Sidebar: buscamos un tono oscuro con el matiz de la marca
  // que cumpla contraste >= 7.0:1 contra el texto claro (#F8FAFC).
  const sFondo = Math.min(hsl.s, 0.48)
  let lFondo = Math.min(hsl.l, 0.18)

  while (lFondo > 0.02) {
    const rgbTest = hslToRgb(hsl.h, sFondo, lFondo)
    const ratio = calcularContrastRatio(rgbTextoClaro, rgbTest)
    if (ratio >= 7.0) break
    lFondo -= 0.005
  }
  const rgbFondo = hslToRgb(hsl.h, sFondo, lFondo)

  // 2. Superficie Activa (ítem seleccionado): ligeramente más clara que el fondo,
  // garantizando contraste >= 4.5:1 contra el texto claro.
  const sSuperficie = Math.min(hsl.s, 0.45)
  let lSuperficie = Math.min(lFondo + 0.07, 0.28)

  while (lSuperficie > lFondo) {
    const rgbTest = hslToRgb(hsl.h, sSuperficie, lSuperficie)
    const ratio = calcularContrastRatio(rgbTextoClaro, rgbTest)
    if (ratio >= 4.5) break
    lSuperficie -= 0.005
  }
  const rgbSuperficie = hslToRgb(hsl.h, sSuperficie, lSuperficie)

  // 3. Borde sutil
  const rgbBorde = hslToRgb(hsl.h, sFondo, Math.min(lFondo + 0.05, 0.22))

  // 4. Acento de marca (indicador lateral / badge / toggle)
  const sAcento = Math.max(hsl.s, 0.70)
  const lAcento = Math.min(Math.max(hsl.l, 0.45), 0.65)
  const rgbAcento = hslToRgb(hsl.h, sAcento, lAcento)

  const hexFondo = rgbToHex(rgbFondo.r, rgbFondo.g, rgbFondo.b)
  const hexSuperficie = rgbToHex(rgbSuperficie.r, rgbSuperficie.g, rgbSuperficie.b)
  const hexBorde = rgbToHex(rgbBorde.r, rgbBorde.g, rgbBorde.b)
  const hexAcento = rgbToHex(rgbAcento.r, rgbAcento.g, rgbAcento.b)

  // 5. Gradient Mesh visible y dimensional con esferas de luz orgánicas (inspirado en tarjetas modernas)
  const meshBg = [
    // Esfera superior derecha (aura circular definida y suave como en la referencia)
    `radial-gradient(circle 260px at 95% 10%, rgba(${rgbAcento.r}, ${rgbAcento.g}, ${rgbAcento.b}, 0.42) 0%, rgba(${rgbAcento.r}, ${rgbAcento.g}, ${rgbAcento.b}, 0.15) 60%, transparent 100%)`,
    // Esfera inferior derecha (segunda burbuja de luz envolvente)
    `radial-gradient(circle 280px at 100% 90%, rgba(${rgbAcento.r}, ${rgbAcento.g}, ${rgbAcento.b}, 0.34) 0%, rgba(${rgbAcento.r}, ${rgbAcento.g}, ${rgbAcento.b}, 0.10) 65%, transparent 100%)`,
    // Reflejo blanco etéreo sobre el cuadrante superior (aporta volumen de iluminación)
    `radial-gradient(circle 160px at 85% 14%, rgba(255, 255, 255, 0.08) 0%, transparent 60%)`,
    // Foco de iluminación ambiental suave en el cuadrante superior izquierdo
    `radial-gradient(circle 240px at 0% 15%, rgba(${rgbAcento.r}, ${rgbAcento.g}, ${rgbAcento.b}, 0.25) 0%, transparent 70%)`,
    // Lavado vertical suave que integra los focos de luz
    `linear-gradient(180deg, rgba(${rgbAcento.r}, ${rgbAcento.g}, ${rgbAcento.b}, 0.12) 0%, transparent 35%)`,
    hexFondo,
  ].join(', ')

  return {
    '--tenant-sidebar-bg': hexFondo,
    '--tenant-sidebar-surface': hexSuperficie,
    '--tenant-sidebar-border': hexBorde,
    '--tenant-sidebar-accent': hexAcento,
    '--tenant-sidebar-text': TEXTO_CLARO_SIDEBAR,
    '--tenant-sidebar-text-muted': '#CBD5E1',
    '--tenant-sidebar-mesh-bg': meshBg,
  }
}

/**
 * Pre-procesamiento en cliente con <canvas>:
 * 1. Redimensiona proporcionalmente a máximo 256x256.
 * 2. Exporta a image/webp con calidad optimizada.
 * 3. Extrae el color dominante descartando transparencias, blancos y negros.
 */
export async function procesarImagenLogo(archivo: File): Promise<{
  archivoWebp: File
  colorDominante: string
  previewUrl: string
}> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('No se pudo leer el archivo seleccionado.'))
    reader.onload = () => {
      const img = new Image()
      img.onerror = () => reject(new Error('El archivo no contiene una imagen válida.'))
      img.onload = () => {
        try {
          const maxDim = 256
          let { width, height } = img

          if (width > maxDim || height > maxDim) {
            const ratio = Math.min(maxDim / width, maxDim / height)
            width = Math.round(width * ratio)
            height = Math.round(height * ratio)
          }

          const canvas = document.createElement('canvas')
          canvas.width = width
          canvas.height = height
          const ctx = canvas.getContext('2d', { willReadFrequently: true })

          if (!ctx) {
            reject(new Error('No se pudo inicializar el contexto 2D para optimizar la imagen.'))
            return
          }

          ctx.drawImage(img, 0, 0, width, height)

          // Extraer color dominante de los píxeles
          const imageData = ctx.getImageData(0, 0, width, height).data
          let rTotal = 0
          let gTotal = 0
          let bTotal = 0
          let pixelesValidos = 0
          let mayorSaturacion = -1
          let colorMasSaturado = { r: 79, g: 70, b: 229 } // Fallback Índigo

          for (let i = 0; i < imageData.length; i += 16) { // Muestreo cada 4 píxeles
            const r = imageData[i]
            const g = imageData[i + 1]
            const b = imageData[i + 2]
            const a = imageData[i + 3]

            // Descartar píxeles transparentes
            if (a < 128) continue

            // Descartar casi blancos y casi negros
            const brillo = 0.299 * r + 0.587 * g + 0.114 * b
            if (brillo > 230 || brillo < 25) continue

            rTotal += r
            gTotal += g
            bTotal += b
            pixelesValidos++

            const hslPixel = rgbToHsl(r, g, b)
            if (hslPixel.s > mayorSaturacion) {
              mayorSaturacion = hslPixel.s
              colorMasSaturado = { r, g, b }
            }
          }

          let colorHex = '#4F46E5'
          if (mayorSaturacion > 0.25) {
            colorHex = rgbToHex(colorMasSaturado.r, colorMasSaturado.g, colorMasSaturado.b)
          } else if (pixelesValidos > 0) {
            colorHex = rgbToHex(
              Math.round(rTotal / pixelesValidos),
              Math.round(gTotal / pixelesValidos),
              Math.round(bTotal / pixelesValidos)
            )
          }

          // Exportar a WebP
          canvas.toBlob(
            (blob) => {
              if (!blob) {
                reject(new Error('No se pudo exportar la imagen optimizada a formato WebP.'))
                return
              }
              const archivoWebp = new File([blob], 'logo.webp', { type: 'image/webp' })
              const previewUrl = URL.createObjectURL(blob)
              resolve({
                archivoWebp,
                colorDominante: colorHex,
                previewUrl,
              })
            },
            'image/webp',
            0.85
          )
        } catch (err) {
          reject(err)
        }
      }
      img.src = String(reader.result)
    }
    reader.readAsDataURL(archivo)
  })
}

