// Formulario compartido para crear y editar medicamentos.
// Las validaciones del cliente son espejo de las del backend
// (schemas/medications.py): nombre obligatorio 1-150 caracteres,
// presentacion <=100, concentracion <=50, unidad <=30, notas libres.
// Si el servidor responde 422, se muestra su mensaje tal cual.
//
// En edicion solo se envian los campos que cambiaron: el backend
// usa `model_dump(exclude_unset=True)` y un campo en null lo borra,
// asi que enviar lo que no cambio podria borrar datos sin querer.

import { useState } from "react";
import { ApiError } from "../services/api";
import {
  createMedication,
  updateMedication,
  type Medication,
  type MedicationCreateInput,
  type MedicationUpdateInput,
} from "../services/medications";

const MAX_NAME = 150;
const MAX_PRESENTATION = 100;
const MAX_CONCENTRATION = 50;
const MAX_UNIT = 30;

function fieldErrors(values: {
  name: string;
  presentation: string;
  concentration: string;
  unit: string;
}): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!values.name.trim()) {
    errors.name = "El nombre es obligatorio.";
  } else if (values.name.trim().length > MAX_NAME) {
    errors.name = `El nombre no puede tener más de ${MAX_NAME} caracteres.`;
  }
  if (values.presentation.length > MAX_PRESENTATION) {
    errors.presentation = `La presentación no puede tener más de ${MAX_PRESENTATION} caracteres.`;
  }
  if (values.concentration.length > MAX_CONCENTRATION) {
    errors.concentration = `La concentración no puede tener más de ${MAX_CONCENTRATION} caracteres.`;
  }
  if (values.unit.length > MAX_UNIT) {
    errors.unit = `La unidad no puede tener más de ${MAX_UNIT} caracteres.`;
  }
  return errors;
}

export default function MedicationForm({
  initial,
  onSaved,
  onCancel,
}: {
  initial?: Medication | null;
  onSaved: (med: Medication) => void;
  onCancel: () => void;
}) {
  const editing = Boolean(initial);
  const [name, setName] = useState(initial?.name ?? "");
  const [presentation, setPresentation] = useState(
    initial?.presentation ?? "",
  );
  const [concentration, setConcentration] = useState(
    initial?.concentration ?? "",
  );
  const [unit, setUnit] = useState(initial?.unit ?? "");
  const [notes, setNotes] = useState(initial?.notes ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const values = { name, presentation, concentration, unit };
    const found = fieldErrors(values);
    setErrors(found);
    setServerError(null);
    setNotice(null);
    if (Object.keys(found).length > 0) {
      return;
    }

    if (editing && initial) {
      // Solo lo que cambio, para no borrar campos sin querer.
      const payload: MedicationUpdateInput = {};
      if (name.trim() !== initial.name) {
        payload.name = name.trim();
      }
      if ((presentation.trim() || null) !== initial.presentation) {
        payload.presentation = presentation.trim() || null;
      }
      if ((concentration.trim() || null) !== initial.concentration) {
        payload.concentration = concentration.trim() || null;
      }
      if ((unit.trim() || null) !== initial.unit) {
        payload.unit = unit.trim() || null;
      }
      if ((notes.trim() || null) !== initial.notes) {
        payload.notes = notes.trim() || null;
      }
      if (Object.keys(payload).length === 0) {
        setNotice("Sin cambios que guardar.");
        return;
      }
      setSaving(true);
      try {
        const saved = await updateMedication(initial.id, payload);
        onSaved(saved);
      } catch (error) {
        setServerError(
          error instanceof ApiError
            ? error.message
            : "No se pudo guardar el medicamento.",
        );
      } finally {
        setSaving(false);
      }
      return;
    }

    const payload: MedicationCreateInput = { name: name.trim() };
    if (presentation.trim()) {
      payload.presentation = presentation.trim();
    }
    if (concentration.trim()) {
      payload.concentration = concentration.trim();
    }
    if (unit.trim()) {
      payload.unit = unit.trim();
    }
    if (notes.trim()) {
      payload.notes = notes.trim();
    }
    setSaving(true);
    try {
      const saved = await createMedication(payload);
      onSaved(saved);
    } catch (error) {
      setServerError(
        error instanceof ApiError
          ? error.message
          : "No se pudo crear el medicamento.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="form" onSubmit={handleSubmit}>
      <div className="field">
        <label htmlFor="med-name">Nombre *</label>
        <input
          id="med-name"
          type="text"
          value={name}
          maxLength={MAX_NAME}
          onChange={(event) => setName(event.target.value)}
          placeholder="Paracetamol"
        />
        {errors.name ? (
          <p className="field-error">{errors.name}</p>
        ) : (
          <p className="hint">Obligatorio, hasta 150 caracteres.</p>
        )}
      </div>

      <div className="field">
        <label htmlFor="med-presentation">Presentación</label>
        <input
          id="med-presentation"
          type="text"
          value={presentation}
          maxLength={MAX_PRESENTATION}
          onChange={(event) => setPresentation(event.target.value)}
          placeholder="Tableta"
        />
        {errors.presentation ? (
          <p className="field-error">{errors.presentation}</p>
        ) : (
          <p className="hint">Opcional, hasta 100 caracteres.</p>
        )}
      </div>

      <div className="field">
        <label htmlFor="med-concentration">Concentración</label>
        <input
          id="med-concentration"
          type="text"
          value={concentration}
          maxLength={MAX_CONCENTRATION}
          onChange={(event) => setConcentration(event.target.value)}
          placeholder="500 mg"
        />
        {errors.concentration ? (
          <p className="field-error">{errors.concentration}</p>
        ) : (
          <p className="hint">Opcional, hasta 50 caracteres.</p>
        )}
      </div>

      <div className="field">
        <label htmlFor="med-unit">Unidad</label>
        <input
          id="med-unit"
          type="text"
          value={unit}
          maxLength={MAX_UNIT}
          onChange={(event) => setUnit(event.target.value)}
          placeholder="tableta"
        />
        {errors.unit ? (
          <p className="field-error">{errors.unit}</p>
        ) : (
          <p className="hint">Opcional, hasta 30 caracteres.</p>
        )}
      </div>

      <div className="field">
        <label htmlFor="med-notes">Notas</label>
        <textarea
          id="med-notes"
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          placeholder="Indicaciones, observaciones…"
        />
        <p className="hint">Opcional.</p>
      </div>

      {serverError ? <p className="error">{serverError}</p> : null}
      {notice ? <p className="hint">{notice}</p> : null}

      <button id="med-submit" type="submit" disabled={saving}>
        {saving
          ? "Guardando…"
          : editing
            ? "Guardar cambios"
            : "Guardar medicamento"}
      </button>
      <button type="button" className="btn-ghost" onClick={onCancel}>
        Cancelar
      </button>
    </form>
  );
}
