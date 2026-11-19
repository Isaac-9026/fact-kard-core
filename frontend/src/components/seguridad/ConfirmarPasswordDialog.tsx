/**
 * Ventana "Confirme su contraseña" para acciones críticas (anular comprobante, reabrir período,
 * recalcular Kardex). La abre el cliente HTTP cuando el backend lo pide; al confirmar, la misma
 * acción se reintenta con la contraseña. Se monta una sola vez en el layout principal.
 */
import { useEffect, useRef, useState } from 'react'
import { ShieldCheck } from 'lucide-react'
import { Modal } from '../ui/modal'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import { registrarPedirPassword } from '../../api/http'

interface Pedido {
  mensaje: string
  resolver: (password: string | null) => void
}

export function ConfirmarPasswordDialog() {
  const [pedido, setPedido] = useState<Pedido | null>(null)
  const [password, setPassword] = useState('')
  const pedidoRef = useRef<Pedido | null>(null)

  useEffect(() => registrarPedirPassword((mensaje) => new Promise<string | null>((resolver) => {
    pedidoRef.current?.resolver(null) // un pedido anterior sin responder se cancela
    const nuevo = { mensaje, resolver }
    pedidoRef.current = nuevo
    setPassword('')
    setPedido(nuevo)
  })), [])

  const responder = (valor: string | null) => {
    pedidoRef.current?.resolver(valor)
    pedidoRef.current = null
    setPedido(null)
    setPassword('')
  }

  const incorrecta = pedido?.mensaje.toLowerCase().includes('incorrecta')

  return (
    <Modal
      isOpen={pedido !== null}
      onClose={() => responder(null)}
      title="Confirme su contraseña"
      description="Esta acción no se puede deshacer fácilmente. Por seguridad, ingrese su contraseña."
      icon={<ShieldCheck className="h-5 w-5" />}
      maxWidth="sm"
    >
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (password) responder(password)
        }}
      >
        {incorrecta && (
          <p className="rounded-md border border-rose-200 bg-rose-50 p-2 text-xs font-medium text-rose-800">
            {pedido?.mensaje}
          </p>
        )}
        <div className="space-y-1">
          <Label htmlFor="confirmar-password" required>Contraseña</Label>
          <Input
            id="confirmar-password"
            type="password"
            autoComplete="current-password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => responder(null)}>Cancelar</Button>
          <Button type="submit" variant="primary" disabled={!password}>Confirmar</Button>
        </div>
      </form>
    </Modal>
  )
}
