import React from 'react';
import { Modal } from '../../components/ui/modal';
import { Button } from '../../components/ui/button';
import { Lock, ShieldCheck, AlertTriangle, Loader2 } from 'lucide-react';

interface ModalConfirmarCierreProps {
  abierto: boolean;
  periodo: { anio: number; mes: number } | null;
  enviando: boolean;
  onConfirmar: () => void;
  onCancelar: () => void;
}

const etiqueta = (p: { anio: number; mes: number }) => `${p.anio}-${String(p.mes).padStart(2, '0')}`;

export const ModalConfirmarCierre: React.FC<ModalConfirmarCierreProps> = ({
  abierto,
  periodo,
  enviando,
  onConfirmar,
  onCancelar,
}) => {
  if (!periodo) return null;

  return (
    <Modal
      isOpen={abierto}
      onClose={onCancelar}
      maxWidth="md"
      icon={
        <div className="p-2 rounded-lg bg-emerald-50 text-emerald-700 border border-emerald-200">
          <Lock className="h-5 w-5" />
        </div>
      }
      title="Confirmar Cierre Oficial de Período"
      description={`Período contable a congelar: ${etiqueta(periodo)}`}
      footer={
        <div className="flex items-center justify-end gap-2 w-full">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={enviando}
            onClick={onCancelar}
          >
            Cancelar
          </Button>
          <Button
            type="button"
            variant="primary"
            size="sm"
            disabled={enviando}
            onClick={onConfirmar}
            className="bg-emerald-600 hover:bg-emerald-700 text-white shadow-xs"
          >
            {enviando ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
            ) : (
              <Lock className="h-3.5 w-3.5 mr-1.5" />
            )}
            {enviando ? 'Ejecutando Cierre...' : 'Confirmar Cierre Oficial'}
          </Button>
        </div>
      }
    >
      <div className="space-y-3.5 text-xs">
        <div className="rounded-lg border border-slate-200 bg-slate-50/70 p-3 space-y-2">
          <span className="font-semibold text-slate-800 block">
            Efectos del Cierre en el Sistema:
          </span>
          <ul className="space-y-1.5 text-slate-600">
            <li className="flex items-start gap-2">
              <ShieldCheck className="h-4 w-4 text-emerald-600 shrink-0 mt-0.5" />
              <span>
                <strong>Inmutabilidad Contable:</strong> Se congelan todos los movimientos y comprobantes del período {etiqueta(periodo)}.
              </span>
            </li>
            <li className="flex items-start gap-2">
              <ShieldCheck className="h-4 w-4 text-emerald-600 shrink-0 mt-0.5" />
              <span>
                <strong>Snapshot Oficial:</strong> Se calculan y guardan los saldos finales y CPP exacto por producto y almacén.
              </span>
            </li>
            <li className="flex items-start gap-2">
              <ShieldCheck className="h-4 w-4 text-emerald-600 shrink-0 mt-0.5" />
              <span>
                <strong>Firma Criptográfica:</strong> Se generará un sello de integridad digital con algoritmo <strong>SHA-256</strong>.
              </span>
            </li>
          </ul>
        </div>

        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-800 flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
          <p>
            <strong>Aviso de Auditoría:</strong> Una vez cerrado, no se podrán agregar ni modificar documentos en este mes a menos que un administrador ejecute una reapertura formal justificada.
          </p>
        </div>
      </div>
    </Modal>
  );
};

export default ModalConfirmarCierre;

