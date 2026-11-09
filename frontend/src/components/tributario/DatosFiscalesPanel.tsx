/**
 * Bloque 17A — datos fiscales del emisor (empresa activa): domicilio fiscal, ubigeo y país,
 * con la validación previa a la emisión electrónica. El RUC no se edita aquí.
 */
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { FileBadge, Save } from 'lucide-react'
import { actualizarDatosFiscales, obtenerDatosFiscales, type DatosFiscales } from '../../api/empresas'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../ui/card'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import { AlertaFormulario } from '../ui/alerta-formulario'
import { ResultadoValidacion } from './ResultadoValidacion'
import { ConsultaRucEstadoCard } from '../consultaRuc/ConsultaRucEstadoCard'
import { ConsultaRucBoton } from '../consultaRuc/ConsultaRucBoton'
import { MAPA_DATOS_FISCALES } from '../../utils/consultaRuc'
import { mensajesDeErrorApi } from '../../utils/errores'
import { diferirCarga } from '../../utils/efectos'
import { errorUbigeo } from '../../utils/tributario'

type Formulario = Record<'razon_social' | 'nombre_comercial' | 'direccion' | 'ubigeo' | 'departamento' | 'provincia' | 'distrito' | 'codigo_pais', string>

const aFormulario = (d: DatosFiscales): Formulario => ({
  razon_social: d.razon_social ?? '', nombre_comercial: d.nombre_comercial ?? '', direccion: d.direccion ?? '',
  ubigeo: d.ubigeo ?? '', departamento: d.departamento ?? '', provincia: d.provincia ?? '', distrito: d.distrito ?? '',
  codigo_pais: d.codigo_pais ?? 'PE',
})

const CAMPOS: { campo: keyof Formulario; etiqueta: string; requerido?: boolean; max: number; ancho?: string; placeholder?: string }[] = [
  { campo: 'razon_social', etiqueta: 'Razón social', requerido: true, max: 200, ancho: 'sm:col-span-2' },
  { campo: 'nombre_comercial', etiqueta: 'Nombre comercial', max: 200, ancho: 'sm:col-span-2' },
  { campo: 'direccion', etiqueta: 'Domicilio fiscal', requerido: true, max: 300, ancho: 'sm:col-span-2', placeholder: 'AV. / JR. / CALLE, número' },
  { campo: 'ubigeo', etiqueta: 'Ubigeo (INEI)', requerido: true, max: 6, placeholder: '150101' },
  { campo: 'codigo_pais', etiqueta: 'País', requerido: true, max: 2, placeholder: 'PE' },
  { campo: 'departamento', etiqueta: 'Departamento', requerido: true, max: 100 },
  { campo: 'provincia', etiqueta: 'Provincia', requerido: true, max: 100 },
  { campo: 'distrito', etiqueta: 'Distrito', requerido: true, max: 100 },
]

export function DatosFiscalesPanel({ esAdmin }: { esAdmin: boolean }) {
  const [datos, setDatos] = useState<DatosFiscales | null>(null)
  const [form, setForm] = useState<Formulario | null>(null)
  const [errores, setErrores] = useState<string[] | null>(null)
  const [aviso, setAviso] = useState('')
  const [guardando, setGuardando] = useState(false)

  const cargar = useCallback(async () => {
    try {
      const d = await obtenerDatosFiscales()
      setDatos(d)
      setForm(aFormulario(d))
    } catch (e) {
      setErrores(mensajesDeErrorApi(e, 'No se pudieron cargar los datos fiscales.'))
    }
  }, [])
  useEffect(() => { diferirCarga(cargar) }, [cargar])

  const guardar = async (event: FormEvent) => {
    event.preventDefault()
    if (!form) return
    setErrores(null)
    setAviso('')
    const errUbigeo = form.ubigeo.trim() ? errorUbigeo(form.ubigeo.trim()) : null
    if (errUbigeo) return setErrores([errUbigeo])
    setGuardando(true)
    try {
      const d = await actualizarDatosFiscales({
        ...form, ubigeo: form.ubigeo.trim() || null, codigo_pais: form.codigo_pais.trim().toUpperCase(),
      })
      setDatos(d)
      setForm(aFormulario(d))
      setAviso('Datos fiscales actualizados.')
    } catch (e) {
      setErrores(mensajesDeErrorApi(e, 'No se pudieron guardar los datos fiscales.'))
    } finally {
      setGuardando(false)
    }
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><FileBadge className="h-4 w-4" /> Datos fiscales del emisor</CardTitle>
          <CardDescription>Identifican a la empresa en la futura factura electrónica. RUC: <span className="font-mono">{datos?.ruc ?? '—'}</span> (no editable).</CardDescription>
        </CardHeader>
        <CardContent>
          {form && (
            <form onSubmit={guardar} className="grid grid-cols-1 gap-3 sm:grid-cols-2" data-testid="form-datos-fiscales">
              {esAdmin && datos && (
                <div className="sm:col-span-2">
                  {/* Bloque 17C: completa con los datos del RUC de la empresa; luego "Guardar datos fiscales". */}
                  <ConsultaRucBoton ruc={datos.ruc} formulario={form} campos={MAPA_DATOS_FISCALES} onAplicar={setForm} />
                </div>
              )}
              {CAMPOS.map(({ campo, etiqueta, requerido, max, ancho, placeholder }) => (
                <div key={campo} className={`space-y-1.5 ${ancho ?? ''}`}>
                  <Label required={requerido} htmlFor={`df-${campo}`}>{etiqueta}</Label>
                  <Input
                    id={`df-${campo}`}
                    maxLength={max}
                    placeholder={placeholder}
                    disabled={!esAdmin}
                    className={campo === 'ubigeo' || campo === 'codigo_pais' ? 'font-mono tabular-nums uppercase' : ''}
                    value={form[campo]}
                    onChange={(e) => setForm({ ...form, [campo]: e.target.value })}
                  />
                </div>
              ))}
              {errores && <div className="sm:col-span-2"><AlertaFormulario titulo="No se pudo guardar" mensajes={errores} /></div>}
              {aviso && <p className="text-xs text-emerald-700 sm:col-span-2" role="status">{aviso}</p>}
              {esAdmin && (
                <div className="sm:col-span-2">
                  <Button type="submit" variant="primary" isLoading={guardando}><Save className="h-4 w-4" /> Guardar datos fiscales</Button>
                </div>
              )}
            </form>
          )}
        </CardContent>
      </Card>
      <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Preparación del emisor</CardTitle>
          <CardDescription>Requisitos previos; todavía no se conecta a SUNAT.</CardDescription>
        </CardHeader>
        <CardContent>
          {datos && (
            <ResultadoValidacion
              {...datos.validacion}
              etiquetaListo="Emisor completo"
              etiquetaNoListo="Faltan datos del emisor"
            />
          )}
        </CardContent>
      </Card>
      {/* Bloque 17D: fuente de la consulta RUC (padrón SUNAT), solo metadatos, solo ADMIN. */}
      {esAdmin && <ConsultaRucEstadoCard />}
      </div>
    </div>
  )
}
