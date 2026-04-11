"""Constraint diagnostics and infeasibility negotiator.

This is the killer feature: when the solver finishes (feasible or not),
the system EXPLAINS why in engineer language and SUGGESTS fixes.

Two main entry points:
  - diagnose_feasible(model): extract shadow prices, identify bottlenecks
  - diagnose_infeasible(config, plan): build elastic LP, return InfeasibilityReport
"""

from __future__ import annotations

import os
import sys
from typing import Any, Optional

import pyomo.environ as pyo

from eurekan.core.config import RefineryConfig
from eurekan.core.period import PlanDefinition
from eurekan.core.results import (
    ConstraintDiagnostic,
    InfeasibilityReport,
)
from eurekan.optimization.builder import (
    _BLEND_COMPONENT_PROPS,
    _DEFAULT_AROMATICS_MAX,
    _DEFAULT_BENZENE_MAX,
    _DEFAULT_OCTANE_MIN,
    _DEFAULT_OLEFINS_MAX,
    _DEFAULT_RVP_MAX,
    _DEFAULT_SULFUR_MAX,
    _RVP_EXP,
    PyomoModelBuilder,
)

# Constraints whose shadow price tells the engineer something useful
_DISPLAY_NAMES: dict[str, str] = {
    "cdu_capacity_con": "CDU Capacity",
    "fcc_capacity_con": "FCC Capacity",
    "fcc_regen_temp_con": "FCC Regenerator Temperature",
    "fcc_gas_compressor_con": "FCC Gas Compressor",
    "fcc_air_blower_con": "FCC Air Blower",
    "octane_spec": "Gasoline Octane (RON)",
    "rvp_spec": "Gasoline RVP",
    "sulfur_spec": "Gasoline Sulfur",
    "benzene_spec": "Gasoline Benzene",
    "aromatics_spec": "Gasoline Aromatics",
    "olefins_spec": "Gasoline Olefins",
    "demand_min_con": "Product Demand (min)",
    "demand_max_con": "Product Demand (max)",
}

# Approximate $/unit relaxation cost for the most actionable constraints
# These are heuristic estimates used to rank "cheapest fix first"
_RELAXATION_COSTS: dict[str, float] = {
    "octane_spec": 5000.0,       # $/(RON-bbl) — buying reformate
    "rvp_spec": 2000.0,           # $/(psi-bbl)
    "sulfur_spec": 8000.0,        # $/(wt%-bbl)
    "benzene_spec": 3000.0,
    "aromatics_spec": 1500.0,
    "olefins_spec": 1500.0,
}

# Source-stream attribution: which stream contributes most to each constraint
_SOURCE_STREAMS: dict[str, str] = {
    "octane_spec": "gasoline blend pool",
    "rvp_spec": "gasoline blend pool (n-butane)",
    "sulfur_spec": "gasoline blend pool (FCC heavy naphtha)",
    "benzene_spec": "reformate + light naphtha",
    "aromatics_spec": "reformate + FCC heavy naphtha",
    "olefins_spec": "FCC light naphtha",
    "fcc_regen_temp_con": "FCC feed CCR",
    "fcc_air_blower_con": "FCC feed CCR",
    "fcc_gas_compressor_con": "FCC conversion",
    "cdu_capacity_con": "crude slate",
    "fcc_capacity_con": "VGO routing",
}


def _humanize(name: str) -> str:
    """Return a human-readable display name for a constraint base name."""
    return _DISPLAY_NAMES.get(name, name.replace("_", " ").title())


def _bi(ron: float) -> float:
    return -36.1572 + 0.83076 * ron + 0.0037397 * ron * ron


# ---------------------------------------------------------------------------
# ConstraintDiagnostician
# ---------------------------------------------------------------------------


class ConstraintDiagnostician:
    """Extracts and interprets constraint information after a solve."""

    BINDING_TOLERANCE = 1e-4

    # ------------------------------------------------------------------
    # Feasible diagnostics — shadow prices and bottlenecks
    # ------------------------------------------------------------------

    def diagnose_feasible(
        self, model: pyo.ConcreteModel
    ) -> list[ConstraintDiagnostic]:
        """Extract shadow prices from a solved (feasible) model.

        Returns a list of ConstraintDiagnostic sorted by bottleneck_score
        (highest first). The first entry is the constraint that most
        limits profitability.
        """
        if not hasattr(model, "dual"):
            return []

        diagnostics: list[ConstraintDiagnostic] = []

        for con_obj in model.component_objects(pyo.Constraint, active=True):
            base_name = con_obj.name
            for index in con_obj:
                con_data = con_obj[index]
                try:
                    dual = float(model.dual.get(con_data, 0.0))
                except Exception:
                    dual = 0.0

                try:
                    body_val = float(pyo.value(con_data.body))
                except Exception:
                    body_val = 0.0

                upper_val: Optional[float]
                lower_val: Optional[float]
                try:
                    upper_val = (
                        float(pyo.value(con_data.upper))
                        if con_data.upper is not None
                        else None
                    )
                except Exception:
                    upper_val = None
                try:
                    lower_val = (
                        float(pyo.value(con_data.lower))
                        if con_data.lower is not None
                        else None
                    )
                except Exception:
                    lower_val = None

                is_binding = abs(dual) > self.BINDING_TOLERANCE

                # Compute violation (0 if feasible)
                violation = 0.0
                if upper_val is not None and body_val > upper_val + 1e-6:
                    violation = body_val - upper_val
                if lower_val is not None and body_val < lower_val - 1e-6:
                    violation = lower_val - body_val

                full_name = (
                    f"{base_name}[{index}]" if index is not None else base_name
                )
                display = _humanize(base_name)

                diagnostics.append(
                    ConstraintDiagnostic(
                        constraint_name=full_name,
                        display_name=display,
                        violation=violation,
                        shadow_price=dual,
                        bottleneck_score=0.0,  # filled in below
                        binding=is_binding,
                        source_stream=_SOURCE_STREAMS.get(base_name),
                        relaxation_suggestion=self._suggest_relaxation(base_name, dual)
                        if is_binding
                        else None,
                        relaxation_cost=_RELAXATION_COSTS.get(base_name)
                        if is_binding
                        else None,
                    )
                )

        # Normalize bottleneck scores (0-100 by max |dual|)
        max_dual = max(
            (abs(d.shadow_price or 0.0) for d in diagnostics), default=0.0
        )
        if max_dual > 0:
            for d in diagnostics:
                d.bottleneck_score = round(
                    abs(d.shadow_price or 0.0) / max_dual * 100.0, 2
                )

        diagnostics.sort(key=lambda d: d.bottleneck_score, reverse=True)
        return diagnostics

    def _suggest_relaxation(self, constraint_name: str, shadow_price: float) -> str:
        """Generate an engineer-language relaxation suggestion."""
        display = _humanize(constraint_name)
        if constraint_name == "cdu_capacity_con":
            return (
                f"{display} is binding (shadow price ${shadow_price:.2f}/bbl). "
                f"Each extra bbl/d of CDU throughput is worth ~${shadow_price:.2f}."
            )
        if constraint_name == "fcc_capacity_con":
            return (
                f"{display} is binding. Each extra bbl/d of FCC feed is worth "
                f"~${shadow_price:.2f}."
            )
        if constraint_name == "fcc_regen_temp_con":
            return (
                f"{display} is binding (shadow price ${shadow_price:.2f}/°F). "
                "Lower-CCR feeds or a regen temp upgrade would lift conversion."
            )
        if constraint_name == "fcc_gas_compressor_con":
            return (
                f"{display} is binding. Either lower conversion or upgrade the "
                "wet-gas compressor."
            )
        if constraint_name == "fcc_air_blower_con":
            return (
                f"{display} is binding. Lighter (low-CCR) feed reduces coke and "
                "frees up air blower capacity."
            )
        if constraint_name == "octane_spec":
            return (
                f"{display} is binding. Each additional RON-bbl is worth "
                f"~${abs(shadow_price):.2f}. Consider buying more reformate."
            )
        if constraint_name == "sulfur_spec":
            return (
                f"{display} is binding. Reducing high-sulfur components "
                "(FCC heavy naphtha) or relaxing the spec saves margin."
            )
        if constraint_name == "rvp_spec":
            return (
                f"{display} is binding. Each psi of headroom is worth "
                f"~${abs(shadow_price):.2f}; reducing n-butane in the blend opens it."
            )
        return f"{display} is binding (shadow price ${shadow_price:.4f})."

    # ------------------------------------------------------------------
    # Infeasibility diagnostics — elastic programming
    # ------------------------------------------------------------------

    def diagnose_infeasible(
        self, config: RefineryConfig, plan: PlanDefinition
    ) -> InfeasibilityReport:
        """Build an elastic version of the model and report violations."""
        model = self._build_elastic_model(config, plan)

        ipopt_path = os.path.join(sys.prefix, "Scripts", "ipopt.exe")
        if os.path.exists(ipopt_path):
            solver = pyo.SolverFactory("ipopt", executable=ipopt_path)
        else:
            solver = pyo.SolverFactory("ipopt")
        solver.options["max_iter"] = 3000
        solver.options["tol"] = 1e-6

        try:
            solver.solve(model, tee=False)
        except Exception as exc:
            return InfeasibilityReport(
                is_feasible=False,
                violated_constraints=[],
                suggestions=[f"Elastic solve failed: {exc}"],
                cheapest_fix=None,
            )

        # Read slack variables to identify violations
        violated: list[ConstraintDiagnostic] = []
        spec_names = ["sulfur_spec", "octane_spec", "rvp_spec", "benzene_spec", "aromatics_spec", "olefins_spec"]
        for spec_name in spec_names:
            slack_var = getattr(model, f"{spec_name}_slack", None)
            if slack_var is None:
                continue
            for p in model.PERIODS:
                try:
                    slack_val = float(pyo.value(slack_var[p]))
                except Exception:
                    slack_val = 0.0
                if slack_val > 1e-4:
                    cost = _RELAXATION_COSTS.get(spec_name, 5000.0) * slack_val
                    violated.append(
                        ConstraintDiagnostic(
                            constraint_name=f"{spec_name}[{p}]",
                            display_name=_humanize(spec_name),
                            violation=slack_val,
                            shadow_price=None,
                            bottleneck_score=100.0,
                            binding=True,
                            source_stream=_SOURCE_STREAMS.get(spec_name),
                            relaxation_suggestion=self._infeasibility_suggestion(
                                spec_name, slack_val
                            ),
                            relaxation_cost=cost,
                        )
                    )

        # Sort cheapest fix first
        violated.sort(key=lambda d: d.relaxation_cost or 0.0)

        suggestions = [
            f"Your refinery is infeasible — {len(violated)} spec(s) cannot be met "
            "with the current crude slate and unit configuration."
        ]
        for v in violated:
            if v.relaxation_suggestion:
                suggestions.append(v.relaxation_suggestion)

        cheapest_fix: Optional[str] = None
        if violated:
            cheapest = violated[0]
            cheapest_fix = (
                f"Relax {cheapest.display_name} by {cheapest.violation:.4g} "
                f"(estimated cost ${cheapest.relaxation_cost:.0f})"
                if cheapest.relaxation_cost
                else f"Relax {cheapest.display_name} by {cheapest.violation:.4g}"
            )

        return InfeasibilityReport(
            is_feasible=len(violated) == 0,
            violated_constraints=violated,
            suggestions=suggestions,
            cheapest_fix=cheapest_fix,
        )

    def _infeasibility_suggestion(self, spec_name: str, slack: float) -> str:
        display = _humanize(spec_name)
        return (
            f"{display}: violation = {slack:.4g}. "
            f"Either relax the spec by this amount, or change the crude slate / "
            f"blend recipe to reduce {_SOURCE_STREAMS.get(spec_name, 'the source')}."
        )

    # ------------------------------------------------------------------
    # Elastic model builder
    # ------------------------------------------------------------------

    def _build_elastic_model(
        self, config: RefineryConfig, plan: PlanDefinition
    ) -> pyo.ConcreteModel:
        """Build the planning model with slack variables on every spec.

        The objective is replaced with min(sum of slacks). The optimizer
        finds the smallest set of constraint relaxations that make the
        model feasible.
        """
        builder = PyomoModelBuilder(config, plan)
        m = builder.build()

        # Deactivate the spec constraints we want to make elastic
        spec_names = [
            "sulfur_spec", "octane_spec", "rvp_spec",
            "benzene_spec", "aromatics_spec", "olefins_spec",
        ]
        for name in spec_names:
            con = getattr(m, name, None)
            if con is not None:
                con.deactivate()

        # Add slack variables (one per spec, per period)
        for name in spec_names:
            slack = pyo.Var(
                m.PERIODS,
                within=pyo.NonNegativeReals,
                bounds=(0.0, 1.0e6),
                initialize=0.0,
            )
            setattr(m, f"{name}_slack", slack)

        # Re-add elastic versions of each spec constraint
        self._add_elastic_specs(m, builder, config)

        # Replace the original objective with min(sum slacks)
        m.objective.deactivate()

        slack_sum_expr = sum(
            getattr(m, f"{name}_slack")[p]
            for name in spec_names
            for p in m.PERIODS
        )
        m.slack_objective = pyo.Objective(expr=slack_sum_expr, sense=pyo.minimize)

        return m

    def _add_elastic_specs(
        self,
        m: pyo.ConcreteModel,
        builder: PyomoModelBuilder,
        config: RefineryConfig,
    ) -> None:
        """Re-add the spec constraints with slack absorption."""

        def _spec_value(name: str, kind: str, default: float) -> float:
            return builder._gasoline_spec_value(0, name, kind) if hasattr(
                builder, "_gasoline_spec_value"
            ) else default

        bi = {k: _bi(v["ron"]) for k, v in _BLEND_COMPONENT_PROPS.items()}
        rvp_pow = {k: v["rvp"] ** _RVP_EXP for k, v in _BLEND_COMPONENT_PROPS.items()}

        def _blend_term(model: Any, p: int, attr: str) -> Any:
            return (
                model.ln_to_blend[p] * _BLEND_COMPONENT_PROPS["cdu_ln"][attr]
                + model.hn_to_blend[p] * _BLEND_COMPONENT_PROPS["cdu_hn"][attr]
                + model.fcc_lcn_vol[p] * _BLEND_COMPONENT_PROPS["fcc_lcn"][attr]
                + model.hcn_to_blend[p] * _BLEND_COMPONENT_PROPS["fcc_hcn"][attr]
                + model.nc4_to_blend[p] * _BLEND_COMPONENT_PROPS["n_butane"][attr]
                + model.reformate_purchased[p] * _BLEND_COMPONENT_PROPS["reformate"][attr]
            )

        # Octane (slack adds to BI sum)
        ron_min = _spec_value("road_octane", "min", _DEFAULT_OCTANE_MIN)
        bi_min = _bi(ron_min)

        def octane_elastic(model: Any, p: int) -> Any:
            bi_total = (
                model.ln_to_blend[p] * bi["cdu_ln"]
                + model.hn_to_blend[p] * bi["cdu_hn"]
                + model.fcc_lcn_vol[p] * bi["fcc_lcn"]
                + model.hcn_to_blend[p] * bi["fcc_hcn"]
                + model.nc4_to_blend[p] * bi["n_butane"]
                + model.reformate_purchased[p] * bi["reformate"]
            )
            return bi_total + model.octane_spec_slack[p] >= bi_min * model.gasoline_volume[p]

        m.octane_spec_elastic = pyo.Constraint(m.PERIODS, rule=octane_elastic)

        # RVP (max)
        rvp_max = _spec_value("rvp", "max", _DEFAULT_RVP_MAX)
        rvp_max_pow = rvp_max**_RVP_EXP

        def rvp_elastic(model: Any, p: int) -> Any:
            rvp_total = (
                model.ln_to_blend[p] * rvp_pow["cdu_ln"]
                + model.hn_to_blend[p] * rvp_pow["cdu_hn"]
                + model.fcc_lcn_vol[p] * rvp_pow["fcc_lcn"]
                + model.hcn_to_blend[p] * rvp_pow["fcc_hcn"]
                + model.nc4_to_blend[p] * rvp_pow["n_butane"]
                + model.reformate_purchased[p] * rvp_pow["reformate"]
            )
            return rvp_total <= rvp_max_pow * model.gasoline_volume[p] + model.rvp_spec_slack[p]

        m.rvp_spec_elastic = pyo.Constraint(m.PERIODS, rule=rvp_elastic)

        # Sulfur (max, by weight)
        s_max = _spec_value("sulfur", "max", _DEFAULT_SULFUR_MAX)

        def sulfur_elastic(model: Any, p: int) -> Any:
            def spg_s(c: str) -> float:
                return _BLEND_COMPONENT_PROPS[c]["spg"] * _BLEND_COMPONENT_PROPS[c]["sulfur"]

            def spg(c: str) -> float:
                return _BLEND_COMPONENT_PROPS[c]["spg"]

            wt_sulfur = (
                model.ln_to_blend[p] * spg_s("cdu_ln")
                + model.hn_to_blend[p] * spg_s("cdu_hn")
                + model.fcc_lcn_vol[p] * spg_s("fcc_lcn")
                + model.hcn_to_blend[p] * spg_s("fcc_hcn")
                + model.nc4_to_blend[p] * spg_s("n_butane")
                + model.reformate_purchased[p] * spg_s("reformate")
            )
            wt_total = (
                model.ln_to_blend[p] * spg("cdu_ln")
                + model.hn_to_blend[p] * spg("cdu_hn")
                + model.fcc_lcn_vol[p] * spg("fcc_lcn")
                + model.hcn_to_blend[p] * spg("fcc_hcn")
                + model.nc4_to_blend[p] * spg("n_butane")
                + model.reformate_purchased[p] * spg("reformate")
            )
            return wt_sulfur <= s_max * wt_total + model.sulfur_spec_slack[p]

        m.sulfur_spec_elastic = pyo.Constraint(m.PERIODS, rule=sulfur_elastic)

        # Benzene, aromatics, olefins
        for spec_attr, default_max in (
            ("benzene", _DEFAULT_BENZENE_MAX),
            ("aromatics", _DEFAULT_AROMATICS_MAX),
            ("olefins", _DEFAULT_OLEFINS_MAX),
        ):
            limit = _spec_value(spec_attr, "max", default_max)
            slack_attr = f"{spec_attr}_spec_slack"

            def make_rule(attr: str, lim: float, slack_name: str) -> Any:
                def rule(model: Any, p: int) -> Any:
                    return _blend_term(model, p, attr) <= (
                        lim * model.gasoline_volume[p] + getattr(model, slack_name)[p]
                    )
                return rule

            con_name = f"{spec_attr}_spec_elastic"
            setattr(m, con_name, pyo.Constraint(m.PERIODS, rule=make_rule(spec_attr, limit, slack_attr)))
