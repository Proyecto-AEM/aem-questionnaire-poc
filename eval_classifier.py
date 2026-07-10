#!/usr/bin/env python3
"""
eval_classifier.py -- Evaluacion aislada de classify_cuadro()

Corre el clasificador few-shot sobre todos los casos en data/test_sets/
y reporta accuracy, subtriage y sobre-triage.

Uso:
    python eval_classifier.py
    python eval_classifier.py --zero-shot
    python eval_classifier.py --json-output results/eval_results.json
    python eval_classifier.py --zero-shot --json-output results/eval_results.json
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

# -- Jerarquia clinica: numero mayor = menos urgente --------------------------
ORDEN = {"Clave 1": 0, "Clave 2": 1, "Clave 3": 2}
SEP = "=" * 58
SEP2 = "-" * 58
LABELS = ["Clave 1", "Clave 2", "Clave 3"]


# -- Estructuras de datos -----------------------------------------------------

@dataclass
class CaseResult:
    cuadro: str
    id: int
    expected: str
    got: str | None          # None si la llamada fallo
    justificacion: str
    error: str | None = None

    @property
    def correct(self) -> bool:
        return self.got == self.expected

    @property
    def subtriage(self) -> bool:
        return self.got is not None and ORDEN[self.got] > ORDEN[self.expected]

    @property
    def sobretriage(self) -> bool:
        return self.got is not None and ORDEN[self.got] < ORDEN[self.expected]

    @property
    def fatal(self) -> bool:
        return self.subtriage and self.expected == "Clave 1"


@dataclass
class EvalStats:
    total: int = 0
    correct: int = 0
    subtriage_cases: list[CaseResult] = field(default_factory=list)
    sobretriage_cases: list[CaseResult] = field(default_factory=list)
    error_cases: list[CaseResult] = field(default_factory=list)
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


# -- Carga de datos -----------------------------------------------------------

def load_test_cases() -> list[tuple[str, dict, list[dict]]]:
    datasets = []
    for test_path in sorted(Path("data/test_sets").glob("test_set_*.json")):
        cuadro = test_path.stem.removeprefix("test_set_")
        tree_path = Path(f"trees/{cuadro}.json")
        if not tree_path.exists():
            print(f"  [warn] Tree no encontrado para '{cuadro}', saltando.")
            continue
        tree = json.loads(tree_path.read_text(encoding="utf-8"))
        if tree.get("clasificacion_fija"):
            print(f"  [info] '{cuadro}' tiene clasificacion_fija -- saltando.")
            continue
        examples = json.loads(test_path.read_text(encoding="utf-8"))
        datasets.append((cuadro, tree, examples))
    return datasets


# -- Evaluacion ---------------------------------------------------------------

def run_evaluation(
    client: OpenAI, datasets: list, examples_override: list | None = None
) -> tuple[EvalStats, dict[str, EvalStats], list[CaseResult]]:
    """
    Corre classify_cuadro() sobre todos los casos.
    Si examples_override es lista vacia, corre sin few-shots.
    Si es None, carga los ejemplos normalmente desde data/examples/.
    """
    if not datasets:
        print("\n[Error] No se encontraron datasets para evaluar.")
        sys.exit(1)

    global_stats = EvalStats()
    per_cuadro: dict[str, EvalStats] = {}
    all_results: list[CaseResult] = []

    for cuadro, tree, cases in datasets:
        stats = EvalStats()
        per_cuadro[cuadro] = stats
        print(f"\n  Evaluando {cuadro} ({len(cases)} casos)...")

        for ex in cases:
            case_id = ex.get("id", "?")
            expected = ex.get("clasificacion", "")
            perfil = ex.get("perfil", {})

            try:
                result = classify_cuadro(
                    client, cuadro, tree, perfil, examples=examples_override
                )
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

            if r.error:
                print(f"    #{case_id:>2}  ERROR: {r.error[:60]}")
            elif r.correct:
                print(f"    #{case_id:>2}  OK  {r.got}")
            else:
                tag = "SUBTRIAGE (!)" if r.subtriage else "SOBRE-TRIAGE"
                print(f"    #{case_id:>2}  FAIL  esperado {r.expected} -> obtuvo {r.got}  [{tag}]")

    return global_stats, per_cuadro, all_results


# -- Formateo del reporte -----------------------------------------------------

def _pct(rate: float) -> str:
    return f"{rate * 100:.1f}%"


def print_report(
    global_stats: EvalStats,
    per_cuadro: dict[str, EvalStats],
    titulo: str = "EVALUACION DEL CLASIFICADOR -- AEM",
) -> None:
    s = global_stats
    fatal = s.fatal_cases

    print(f"\n{SEP}")
    print(f"   {titulo}")
    print(SEP)
    print(f"  {'Casos evaluados':<34} {s.evaluated}  ({s.total - len(s.error_cases)} ok, {len(s.error_cases)} error)")
    print(SEP2)
    print(f"  {'Accuracy':<34} {_pct(s.accuracy)}  ({s.correct}/{s.evaluated})")
    print(f"  {'Subtriage (menos urgente)':<34} {_pct(s.subtriage_rate)}  ({len(s.subtriage_cases)} casos)")
    print(f"  {'Sobre-triage (mas urgente)':<34} {_pct(s.sobretriage_rate)}  ({len(s.sobretriage_cases)} casos)")
    print(SEP2)

    if fatal:
        print(f"  (!)  Fatal subtriage Clave 1: {len(fatal)} caso(s) -- CRITICO")
    else:
        print("  OK  Sin subtriage de Clave 1 esperada.")
    print(SEP)

    print("\n  MATRIZ DE CONFUSION")
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

    all_errors = s.subtriage_cases + s.sobretriage_cases + s.error_cases
    print(f"\n  DETALLE DE ERRORES ({len(all_errors)} casos)")
    print(f"  {SEP2}")

    if not all_errors:
        print("  OK Sin errores de clasificacion.")
    else:
        for r in all_errors:
            if r.error:
                print(f"  [{r.cuadro} #{r.id}]  ERROR: {r.error}")
                continue
            tag = "SUBTRIAGE (!)" if r.subtriage else "sobre-triage"
            if r.fatal:
                tag += " -- CLAVE 1 NO DETECTADA"
            print(f"  [{r.cuadro} #{r.id}]  esperado: {r.expected}  ->  obtuvo: {r.got}  ({tag})")
            just = r.justificacion[:120] + ("..." if len(r.justificacion) > 120 else "")
            print(f"    Justificacion modelo: \"{just}\"")

    print(SEP)


def print_comparison(
    stats_fs: tuple[EvalStats, dict],
    stats_zs: tuple[EvalStats, dict],
) -> None:
    g_fs, per_fs = stats_fs
    g_zs, per_zs = stats_zs

    print(f"\n{SEP}")
    print("   COMPARACION FEW-SHOT vs ZERO-SHOT")
    print(SEP)
    print(f"  {'':34}  {'FEW-SHOT':>10}  {'ZERO-SHOT':>10}")
    print(SEP2)
    print(f"  {'Accuracy':<34}  {_pct(g_fs.accuracy):>10}  {_pct(g_zs.accuracy):>10}")
    print(f"  {'Subtriage':<34}  {_pct(g_fs.subtriage_rate):>10}  {_pct(g_zs.subtriage_rate):>10}")
    print(f"  {'Sobre-triage':<34}  {_pct(g_fs.sobretriage_rate):>10}  {_pct(g_zs.sobretriage_rate):>10}")
    print(f"  {'Fatal subtriage (Clave 1)':<34}  {len(g_fs.fatal_cases):>10}  {len(g_zs.fatal_cases):>10}")
    print(SEP2)

    all_cuadros = sorted(set(list(per_fs.keys()) + list(per_zs.keys())))
    print(f"  {'Cuadro':<32}  {'Acc FS':>7}  {'Acc ZS':>7}  {'Sub FS':>7}  {'Sub ZS':>7}")
    print(f"  {SEP2}")
    for cuadro in all_cuadros:
        fs = per_fs.get(cuadro)
        zs = per_zs.get(cuadro)
        acc_fs = _pct(fs.accuracy) if fs else "  N/A"
        acc_zs = _pct(zs.accuracy) if zs else "  N/A"
        sub_fs = _pct(fs.subtriage_rate) if fs else "  N/A"
        sub_zs = _pct(zs.subtriage_rate) if zs else "  N/A"
        print(f"  {cuadro:<32}  {acc_fs:>7}  {acc_zs:>7}  {sub_fs:>7}  {sub_zs:>7}")
    print(SEP)


# -- Salida JSON opcional -----------------------------------------------------

def write_json_output(
    path: str,
    global_stats: EvalStats,
    per_cuadro: dict[str, EvalStats],
    all_results: list[CaseResult],
    mode: str = "few-shot",
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
        "mode": mode,
        "global": stats_dict(global_stats),
        "per_cuadro": {c: stats_dict(st) for c, st in per_cuadro.items()},
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


def write_json_comparison(
    path: str,
    g_fs: EvalStats, per_fs: dict[str, EvalStats], res_fs: list[CaseResult],
    g_zs: EvalStats, per_zs: dict[str, EvalStats], res_zs: list[CaseResult],
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

    def cases_list(results: list[CaseResult]) -> list[dict]:
        return [
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
            for r in results
        ]

    output = {
        "mode": "comparison",
        "few_shot": {
            "global": stats_dict(g_fs),
            "per_cuadro": {c: stats_dict(st) for c, st in per_fs.items()},
            "cases": cases_list(res_fs),
        },
        "zero_shot": {
            "global": stats_dict(g_zs),
            "per_cuadro": {c: stats_dict(st) for c, st in per_zs.items()},
            "cases": cases_list(res_zs),
        },
    }

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n  Resultados guardados en: {out_path}")


# -- Entrypoint ---------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evalua classify_cuadro() sobre los casos de test."
    )
    parser.add_argument(
        "--zero-shot",
        action="store_true",
        help="Corre el test set dos veces -- con few-shots y sin ejemplos -- y compara.",
    )
    parser.add_argument(
        "--json-output",
        metavar="PATH",
        help="Ruta para guardar resultados en JSON (ej: results/eval_results.json)",
    )
    args = parser.parse_args()

    client = OpenAI()

    print(f"\n{SEP}")
    print("  Iniciando evaluacion del clasificador...")

    datasets = load_test_cases()

    if args.zero_shot:
        print("\n  --- Corrida 1: FEW-SHOT (con ejemplos) ---")
        g_fs, per_fs, res_fs = run_evaluation(client, datasets, examples_override=None)
        print_report(g_fs, per_fs, titulo="FEW-SHOT -- con ejemplos")

        print("\n  --- Corrida 2: ZERO-SHOT (sin ejemplos) ---")
        g_zs, per_zs, res_zs = run_evaluation(client, datasets, examples_override=[])
        print_report(g_zs, per_zs, titulo="ZERO-SHOT -- sin ejemplos")

        print_comparison((g_fs, per_fs), (g_zs, per_zs))

        if args.json_output:
            write_json_comparison(args.json_output, g_fs, per_fs, res_fs, g_zs, per_zs, res_zs)
    else:
        g, per, results = run_evaluation(client, datasets, examples_override=None)
        print_report(g, per)

        if args.json_output:
            write_json_output(args.json_output, g, per, results, mode="few-shot")


if __name__ == "__main__":
    main()
