#!/usr/bin/env python3
"""
eval_classifier.py — Evaluación aislada de classify_cuadro()

Corre el clasificador few-shot sobre todos los ejemplos etiquetados en
data/examples_*.json y reporta accuracy, subtriage y sobre-triage.

Uso:
    python eval_classifier.py
    python eval_classifier.py --json-output data/eval_results.json
"""
import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from classifier import classify_cuadro

load_dotenv()

# ── Jerarquía clínica: número mayor = menos urgente ───────────────────────────
ORDEN = {"Clave 1": 0, "Clave 2": 1, "Clave 3": 2}
SEP = "=" * 58
SEP2 = "-" * 58
LABELS = ["Clave 1", "Clave 2", "Clave 3"]


# ── Estructuras de datos ───────────────────────────────────────────────────────

@dataclass
class CaseResult:
    cuadro: str
    id: int
    expected: str
    got: str | None          # None si la llamada falló
    justificacion: str       # justificación devuelta por el modelo
    error: str | None = None # mensaje de error si la llamada falló

    @property
    def correct(self) -> bool:
        return self.got == self.expected

    @property
    def subtriage(self) -> bool:
        """Clasificó con menor urgencia de la correcta — riesgo clínico."""
        return self.got is not None and ORDEN[self.got] > ORDEN[self.expected]

    @property
    def sobretriage(self) -> bool:
        """Clasificó con mayor urgencia de la necesaria — costo operacional."""
        return self.got is not None and ORDEN[self.got] < ORDEN[self.expected]

    @property
    def fatal(self) -> bool:
        """Subtriage donde el expected era Clave 1 — el error más crítico."""
        return self.subtriage and self.expected == "Clave 1"


@dataclass
class EvalStats:
    total: int = 0
    correct: int = 0
    subtriage_cases: list[CaseResult] = field(default_factory=list)
    sobretriage_cases: list[CaseResult] = field(default_factory=list)
    error_cases: list[CaseResult] = field(default_factory=list)
    # confusion[expected][got] = count
    confusion: dict[str, dict[str, int]] = field(
        default_factory=lambda: {
            lbl: {l: 0 for l in LABELS} for lbl in LABELS
        }
    )

    def add(self, r: CaseResult) -> None:
        self.total += 1
        if r.error:
            self.error_cases.append(r)
            return
        if r.correct:
            self.correct += 1
        if r.subtriage:
            self.subtriage_cases.append(r)
        if r.sobretriage:
            self.sobretriage_cases.append(r)
        if r.expected in ORDEN and r.got in ORDEN:
            self.confusion[r.expected][r.got] += 1

    @property
    def evaluated(self) -> int:
        return self.total - len(self.error_cases)

    @property
    def accuracy(self) -> float:
        return self.correct / self.evaluated if self.evaluated else 0.0

    @property
    def subtriage_rate(self) -> float:
        return len(self.subtriage_cases) / self.evaluated if self.evaluated else 0.0

    @property
    def sobretriage_rate(self) -> float:
        return len(self.sobretriage_cases) / self.evaluated if self.evaluated else 0.0

    @property
    def fatal_cases(self) -> list[CaseResult]:
        return [r for r in self.subtriage_cases if r.fatal]


# ── Carga de datos ─────────────────────────────────────────────────────────────

def load_test_cases() -> list[tuple[str, dict, list[dict]]]:
    """
    Devuelve lista de (cuadro, tree, ejemplos) para cada examples_*.json
    que no tenga clasificacion_fija en su tree.
    """
    datasets = []
    for examples_path in sorted(Path("data").glob("test_set_*.json")):
        cuadro = examples_path.stem.removeprefix("test_set_")
        tree_path = Path(f"trees/{cuadro}.json")
        if not tree_path.exists():
            print(f"  [warn] Tree no encontrado para '{cuadro}', saltando.")
            continue
        tree = json.loads(tree_path.read_text(encoding="utf-8"))
        if tree.get("clasificacion_fija"):
            print(f"  [info] '{cuadro}' tiene clasificacion_fija — saltando (no hay nada que evaluar).")
            continue
        examples = json.loads(examples_path.read_text(encoding="utf-8"))
        datasets.append((cuadro, tree, examples))
    return datasets


# ── Evaluación ─────────────────────────────────────────────────────────────────

def run_evaluation(client: OpenAI) -> tuple[EvalStats, dict[str, EvalStats], list[CaseResult]]:
    """
    Corre classify_cuadro() sobre todos los ejemplos etiquetados.
    Retorna (stats_global, stats_por_cuadro, todos_los_resultados).
    """
    datasets = load_test_cases()
    if not datasets:
        print("\n[Error] No se encontraron datasets para evaluar.")
        sys.exit(1)

    global_stats = EvalStats()
    per_cuadro: dict[str, EvalStats] = {}
    all_results: list[CaseResult] = []

    for cuadro, tree, examples in datasets:
        stats = EvalStats()
        per_cuadro[cuadro] = stats
        print(f"\n  Evaluando {cuadro} ({len(examples)} casos)...")

        for ex in examples:
            case_id = ex.get("id", "?")
            expected = ex.get("clasificacion", "")
            perfil = ex.get("perfil", {})

            try:
                result = classify_cuadro(client, cuadro, tree, perfil)
                r = CaseResult(
                    cuadro=cuadro,
                    id=case_id,
                    expected=expected,
                    got=result.clasificacion,
                    justificacion=result.justificacion,
                )
            except Exception as exc:
                r = CaseResult(
                    cuadro=cuadro,
                    id=case_id,
                    expected=expected,
                    got=None,
                    justificacion="",
                    error=str(exc),
                )

            stats.add(r)
            global_stats.add(r)
            all_results.append(r)

            # Feedback inline por caso
            if r.error:
                print(f"    #{case_id:>2}  ERROR: {r.error[:60]}")
            elif r.correct:
                print(f"    #{case_id:>2}  OK  {r.got}")
            else:
                tag = "SUBTRIAGE (!)" if r.subtriage else "SOBRE-TRIAGE"
                print(f"    #{case_id:>2}  ✗  esperado {r.expected} → obtuvo {r.got}  [{tag}]")

    return global_stats, per_cuadro, all_results


# ── Formateo del reporte ───────────────────────────────────────────────────────

def _pct(rate: float) -> str:
    return f"{rate * 100:.1f}%"


def print_report(global_stats: EvalStats, per_cuadro: dict[str, EvalStats]) -> None:
    s = global_stats
    fatal = s.fatal_cases

    print(f"\n{SEP}")
    print("   EVALUACIÓN DEL CLASIFICADOR — AEM")
    print(SEP)
    print(f"  {'Casos evaluados':<34} {s.evaluated}  ({s.total - len(s.error_cases)} ok, {len(s.error_cases)} error)")
    print(SEP2)
    print(f"  {'Accuracy':<34} {_pct(s.accuracy)}  ({s.correct}/{s.evaluated})")
    print(f"  {'Subtriage (menos urgente de lo correcto)':<34} {_pct(s.subtriage_rate)}  ({len(s.subtriage_cases)} casos)")
    print(f"  {'Sobre-triage (más urgente de lo necesario)':<34} {_pct(s.sobretriage_rate)}  ({len(s.sobretriage_cases)} casos)")
    print(SEP2)

    if fatal:
        print(f"  (!)  Subtriage con Clave 1 esperada: {len(fatal)} caso(s) — CRÍTICO")
    else:
        print("  OK  Sin subtriage de Clave 1 esperada.")
    print(SEP)

    # ── Matriz de confusión ───────────────────────────────────────────────────
    print("\n  MATRIZ DE CONFUSIÓN")
    print(f"  {'':16}  {'GOT C1':>8}  {'GOT C2':>8}  {'GOT C3':>8}")
    print(f"  {SEP2}")
    for exp in LABELS:
        row = s.confusion[exp]
        print(
            f"  {'EXP ' + exp:<16}  "
            f"{row['Clave 1']:>8}  "
            f"{row['Clave 2']:>8}  "
            f"{row['Clave 3']:>8}"
        )

    # ── Breakdown por cuadro ──────────────────────────────────────────────────
    print(f"\n  RESULTADOS POR CUADRO")
    print(f"  {'Cuadro':<32}  {'Acc':>6}  {'Sub':>6}  {'Sobre':>6}  {'N':>4}")
    print(f"  {SEP2}")
    for cuadro, st in per_cuadro.items():
        print(
            f"  {cuadro:<32}  "
            f"{_pct(st.accuracy):>6}  "
            f"{_pct(st.subtriage_rate):>6}  "
            f"{_pct(st.sobretriage_rate):>6}  "
            f"{st.evaluated:>4}"
        )

    # ── Detalle de errores ────────────────────────────────────────────────────
    all_errors = s.subtriage_cases + s.sobretriage_cases + s.error_cases
    # Deduplicar (un caso puede ser subtriage y no error, pero no puede estar
    # en dos listas a la vez)
    print(f"\n  DETALLE DE ERRORES ({len(all_errors)} casos)")
    print(f"  {SEP2}")

    if not all_errors:
        print("  OK Sin errores de clasificación.")
    else:
        for r in all_errors:
            if r.error:
                print(f"  [{r.cuadro} #{r.id}]  ERROR: {r.error}")
                continue
            tag = "SUBTRIAGE (!)" if r.subtriage else "sobre-triage"
            if r.fatal:
                tag += " — CLAVE 1 NO DETECTADA"
            print(f"  [{r.cuadro} #{r.id}]  esperado: {r.expected}  →  obtuvo: {r.got}  ({tag})")
            # Truncar justificación para no saturar la pantalla
            just = r.justificacion[:120] + ("…" if len(r.justificacion) > 120 else "")
            print(f"    Justificación modelo: \"{just}\"")

    print(SEP)


# ── Salida JSON opcional ───────────────────────────────────────────────────────

def write_json_output(
    path: str,
    global_stats: EvalStats,
    per_cuadro: dict[str, EvalStats],
    all_results: list[CaseResult],
) -> None:
    def stats_dict(st: EvalStats) -> dict:
        return {
            "total": st.total,
            "evaluated": st.evaluated,
            "correct": st.correct,
            "accuracy": round(st.accuracy, 4),
            "subtriage_count": len(st.subtriage_cases),
            "subtriage_rate": round(st.subtriage_rate, 4),
            "sobretriage_count": len(st.sobretriage_cases),
            "sobretriage_rate": round(st.sobretriage_rate, 4),
            "fatal_subtriage_count": len(st.fatal_cases),
            "confusion_matrix": st.confusion,
        }

    output = {
        "global": stats_dict(global_stats),
        "per_cuadro": {cuadro: stats_dict(st) for cuadro, st in per_cuadro.items()},
        "cases": [
            {
                "cuadro": r.cuadro,
                "id": r.id,
                "expected": r.expected,
                "got": r.got,
                "correct": r.correct,
                "subtriage": r.subtriage,
                "sobretriage": r.sobretriage,
                "fatal": r.fatal,
                "justificacion": r.justificacion,
                "error": r.error,
            }
            for r in all_results
        ],
    }

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n  Resultados guardados en: {out_path}")


# ── Entrypoint ─────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evalúa classify_cuadro() sobre los ejemplos etiquetados."
    )
    parser.add_argument(
        "--json-output",
        metavar="PATH",
        help="Ruta opcional para guardar resultados en JSON (ej: results/eval_results.json)",
    )
    args = parser.parse_args()

    client = OpenAI()

    print(f"\n{SEP}")
    print("  Iniciando evaluación del clasificador...")

    global_stats, per_cuadro, all_results = run_evaluation(client)

    print_report(global_stats, per_cuadro)

    if args.json_output:
        write_json_output(args.json_output, global_stats, per_cuadro, all_results)


if __name__ == "__main__":
    main()
