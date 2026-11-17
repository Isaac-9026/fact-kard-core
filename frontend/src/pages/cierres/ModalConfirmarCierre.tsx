import React, { useState } from 'react';
import { Modal } from '../../components/ui/modal';
import { Button } from '../../components/ui/button';
import { Lock, ShieldCheck, AlertTriangle, Loader2, FileText, Paperclip, X } from 'lucide-react';

interface ModalConfirmarCierreProps {
  abierto: boolean;
  periodo: { anio: number; mes: number } | null;
  enviando: boolean;
  onConfirmar: (archivoPdf?: File | null, referenciaSustento?: string) => void;
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
  const [archivoPdf, setArchivoPdf] = useState<File | null>(null);
  const [referenciaSustento, setReferenciaSustento] = useState('');

  if (!periodo) return null;

  const handleCancelar = () => {
    setArchivoPdf(null);
    setReferenciaSustento('');
    onCancelar();
  };

  const handleConfirmar = () => {
    onConfirmar(archivoPdf, referenciaSustento);
  };

  return (
    <Modal
      isOpen={abierto}
      onClose={handleCancelar}
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
            onClick={handleCancelar}
          >
            Cancelar
          </Button>
          <Button
            type="button"
            variant="primary"
            size="sm"
            disabled={enviando}
            onClick={handleConfirmar}
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

        {/* Sustento de Toma de Inventario Físico (Opcional) */}
        <div className="rounded-lg border border-slate-200 bg-white p-3 space-y-2.5 shadow-2xs">
          <div className="flex items-center gap-1.5 font-semibold text-slate-800">
            <FileText className="h-4 w-4 text-indigo-600" />
            <span>Sustento de Toma de Inventario Físico (Opcional)</span>
          </div>
          <p className="text-[11px] text-slate-500">
            Adjunte el Acta de Toma de Inventario Físico o Informe de Cierre en formato PDF (máx. 5 MB).
          </p>

          <div className="space-y-1">
            <label className="text-[11px] font-medium text-slate-700 block">Referencia / Identificador del Sustento</label>
            <input
              type="text"
              maxLength={200}
              placeholder="Ej. Acta Notarial de Inventario Anual N° 08-2026"
              value={referenciaSustento}
              onChange={(e) => setReferenciaSustento(e.target.value)}
              className="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-900 shadow-2xs focus:ring-2 focus:ring-slate-900 focus:outline-none"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <label className="cursor-pointer inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-300 bg-white text-xs font-semibold text-slate-700 hover:bg-slate-50 shadow-2xs">
              <Paperclip className="h-3.5 w-3.5 text-slate-500" />
              <span>{archivoPdf ? 'Cambiar PDF' : 'Seleccionar PDF de Cierre'}</span>
              <input
                type="file"
                accept=".pdf,application/pdf"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0] || null;
                  if (f && !f.name.toLowerCase().endsWith('.pdf')) {
                    alert('El archivo debe tener extensión .pdf');
                    return;
                  }
                  setArchivoPdf(f);
                }}
              />
            </label>

            {archivoPdf && (
              <div className="flex items-center gap-2 text-xs bg-indigo-50 border border-indigo-200 text-indigo-900 px-2.5 py-1 rounded-md">
                <FileText className="h-3.5 w-3.5 text-indigo-600" />
                <span className="font-mono truncate max-w-[200px]" title={archivoPdf.name}>{archivoPdf.name}</span>
                <button
                  type="button"
                  onClick={() => setArchivoPdf(null)}
                  className="text-slate-400 hover:text-slate-600 ml-1"
                  title="Quitar archivo"
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            )}
          </div>
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

