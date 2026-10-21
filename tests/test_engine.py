import math
import random
import unittest

from mixnavuts.backtest import run_backtest
from mixnavuts.candidates import CandidateConfig, generate_candidates
from mixnavuts.evaluate import Route, evaluate, overlap
from mixnavuts.graph import RoadClass, RoadGraph
from mixnavuts.ranking import MODES, select_routes
from mixnavuts.search import shortest_path, td_fastest_path
from mixnavuts.synthetic import build_city, realize_day
from mixnavuts.traffic import (
    DAY_S,
    FreeFlowTraffic,
    Incident,
    PredictiveTraffic,
    ProfileTraffic,
    SnapshotTraffic,
)

BUCKETS = 96


def flat(factor: float) -> list[float]:
    return [factor] * BUCKETS


def rush(hour_from: float, hour_to: float, factor: float) -> list[float]:
    return [factor if hour_from <= b / 4 < hour_to else 1.0 for b in range(BUCKETS)]


def two_corridors() -> tuple[RoadGraph, dict[str, int]]:
    """A → B by a tolled motorway (fast, jams at 8–9) or a free trunk road."""
    g = RoadGraph()
    a = g.add_node(0, 0, "A")
    b = g.add_node(10_000, 0, "B")
    m1 = g.add_node(3_000, 1_000)
    m2 = g.add_node(7_000, 1_000)
    t1 = g.add_node(5_000, -1_000)
    g.add_edge(a, m1, RoadClass.RAMP, 60, toll_krw=900)
    g.add_edge(m1, m2, RoadClass.MOTORWAY, 100, toll_krw=300)
    g.add_edge(m2, b, RoadClass.RAMP, 60)
    g.add_edge(a, t1, RoadClass.TRUNK, 70)
    g.add_edge(t1, b, RoadClass.TRUNK, 70)
    return g, {"a": a, "b": b, "m1": m1}


class TravelTimeTest(unittest.TestCase):
    def setUp(self) -> None:
        g = RoadGraph()
        u, v = g.add_node(0, 0), g.add_node(36_000, 0)
        self.edge = g.add_edge(u, v, RoadClass.PRIMARY, 72)  # 20 m/s, 30 min free flow

    def test_free_flow(self) -> None:
        self.assertAlmostEqual(FreeFlowTraffic().travel_time(self.edge, 0), 1_800)

    def test_integrates_across_speed_changes(self) -> None:
        # Half speed until 08:00, full speed after. Enter at 07:45:
        # 15 min at 10 m/s = 9 km, the remaining 27 km at 20 m/s = 22.5 min.
        traffic = ProfileTraffic(class_profiles={RoadClass.PRIMARY: rush(0, 8, 0.5)})
        self.assertAlmostEqual(traffic.travel_time(self.edge, 7.75 * 3600), 900 + 1_350)

    def test_fifo(self) -> None:
        rng = random.Random(3)
        profile = [rng.uniform(0.1, 1.0) for _ in range(BUCKETS)]
        traffic = ProfileTraffic(class_profiles={RoadClass.PRIMARY: profile})
        times = sorted(rng.uniform(0, DAY_S) for _ in range(300))
        arrivals = [t + traffic.travel_time(self.edge, t) for t in times]
        self.assertEqual(arrivals, sorted(arrivals))

    def test_profile_wraps_after_midnight(self) -> None:
        traffic = ProfileTraffic(class_profiles={RoadClass.PRIMARY: rush(8, 9, 0.5)})
        self.assertAlmostEqual(traffic.speed_mps(self.edge, 8.5 * 3600), traffic.speed_mps(self.edge, DAY_S + 8.5 * 3600))


class PredictiveTrafficTest(unittest.TestCase):
    def setUp(self) -> None:
        g = RoadGraph()
        u, v = g.add_node(0, 0), g.add_node(1_000, 0)
        self.edge = g.add_edge(u, v, RoadClass.PRIMARY, 72)
        self.historical = ProfileTraffic(class_profiles={RoadClass.PRIMARY: flat(0.8)})  # 16 m/s
        self.now = 8 * 3600

    def test_live_deviation_decays_to_history(self) -> None:
        model = PredictiveTraffic(self.historical, self.now, {self.edge.id: 8.0}, tau_s=1_800)
        self.assertAlmostEqual(model.speed_mps(self.edge, self.now), 8.0)
        later = model.speed_mps(self.edge, self.now + 1_800)
        self.assertAlmostEqual(later, 16.0 * (1 - 0.5 * math.exp(-1)))
        self.assertAlmostEqual(model.speed_mps(self.edge, self.now + 6 * 3600), 16.0, places=2)

    def test_snapshot_stays_frozen(self) -> None:
        model = SnapshotTraffic(self.historical, self.now, {self.edge.id: 8.0})
        self.assertEqual(model.speed_mps(self.edge, self.now + 6 * 3600), 8.0)

    def test_incident_caps_speed_then_clears(self) -> None:
        incident = Incident(frozenset([self.edge.id]), self.now - 600, self.now + 900, 0.1)
        model = PredictiveTraffic(self.historical, self.now, {self.edge.id: 2.0}, incidents=[incident])
        self.assertAlmostEqual(model.speed_mps(self.edge, self.now), 2.0)
        # After the expected clearance the slowdown is not carried forward.
        self.assertAlmostEqual(model.speed_mps(self.edge, self.now + 901), 16.0)
        # Entering just before clearance: 2 m/s until it clears, then 16 m/s.
        self.assertAlmostEqual(model.travel_time(self.edge, self.now + 800), 100 + (1_000 - 200) / 16)


class SearchTest(unittest.TestCase):
    def test_static_shortest_path(self) -> None:
        g, n = two_corridors()
        edges = shortest_path(g, n["a"], n["b"], lambda e: e.length_m)
        self.assertEqual([e.road_class for e in edges], [RoadClass.TRUNK, RoadClass.TRUNK])

    def test_td_search_avoids_jammed_motorway_only_in_rush_hour(self) -> None:
        g, n = two_corridors()
        traffic = ProfileTraffic(class_profiles={RoadClass.MOTORWAY: rush(8, 9, 0.2)})
        off_peak, _ = td_fastest_path(g, n["a"], n["b"], traffic, 13 * 3600)
        peak, _ = td_fastest_path(g, n["a"], n["b"], traffic, 8 * 3600)
        self.assertIn(RoadClass.MOTORWAY, {e.road_class for e in off_peak})
        self.assertNotIn(RoadClass.MOTORWAY, {e.road_class for e in peak})

    def test_td_search_is_optimal_on_city(self) -> None:
        city = build_city(n=12, seed=2)
        day = realize_day(city, random.Random(2))
        s, t = city.intersections[0], city.intersections[-1]
        depart = 8 * 3600
        _, best = td_fastest_path(city.graph, s, t, day.truth, depart)
        for route in generate_candidates(city.graph, s, t, day.truth, depart):
            self.assertGreaterEqual(evaluate(route, day.truth, depart).arrival, best - 1e-6)


class CandidatesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.city = build_city(n=16, seed=4)
        cls.s = cls.city.intersections[0]
        cls.t = cls.city.intersections[-1]
        cls.depart = 8 * 3600
        cls.routes = generate_candidates(cls.city.graph, cls.s, cls.t, cls.city.historical, cls.depart)

    def test_generates_many_unique_connected_routes(self) -> None:
        self.assertGreater(len(self.routes), 100)
        self.assertEqual(len({r.key for r in self.routes}), len(self.routes))
        for route in self.routes:
            self.assertEqual(route.edges[0].source, self.s)
            self.assertEqual(route.edges[-1].target, self.t)
            for prev, nxt in zip(route.edges, route.edges[1:]):
                self.assertEqual(prev.target, nxt.source)
            nodes = [route.edges[0].source, *(e.target for e in route.edges)]
            self.assertEqual(len(nodes), len(set(nodes)), "routes must not loop")

    def test_contains_time_dependent_optimum(self) -> None:
        best, _ = td_fastest_path(self.city.graph, self.s, self.t, self.city.historical, self.depart)
        self.assertIn(tuple(e.id for e in best), {r.key for r in self.routes})

    def test_every_generator_contributes(self) -> None:
        sources = set().union(*(r.sources for r in self.routes))
        self.assertTrue({"fastest", "shortest", "toll_free", "penalty", "via"} <= sources)

    def test_respects_via_limit(self) -> None:
        config = CandidateConfig(max_via=5, penalty_rounds=0)
        routes = generate_candidates(self.city.graph, self.s, self.t, self.city.historical, self.depart, config)
        self.assertLessEqual(sum("via" in r.sources and len(r.sources) == 1 for r in routes), 5)

    def test_unreachable_target(self) -> None:
        g = RoadGraph()
        a, b = g.add_node(0, 0), g.add_node(1, 0)
        self.assertEqual(generate_candidates(g, a, b, FreeFlowTraffic(), 0), [])


class RankingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.g, cls.n = two_corridors()
        routes = generate_candidates(cls.g, cls.n["a"], cls.n["b"], FreeFlowTraffic(), 13 * 3600)
        cls.evals = [evaluate(r, FreeFlowTraffic(), 13 * 3600) for r in routes]

    def test_fastest_is_always_shown(self) -> None:
        fastest = min(self.evals, key=lambda ev: ev.arrival)
        for prefs in MODES.values():
            picks = select_routes(self.evals, prefs, k=2)
            self.assertIn(fastest.route.key, [p.evaluation.route.key for p in picks])

    def test_toll_aversion_changes_the_recommendation(self) -> None:
        fastest_first = select_routes(self.evals, MODES["fastest"])[0]
        economy_first = select_routes(self.evals, MODES["economy"])[0]
        self.assertGreater(fastest_first.evaluation.toll_krw, 0)
        self.assertEqual(economy_first.evaluation.toll_krw, 0)
        self.assertIn("무료도로", economy_first.labels)

    def test_picks_are_diverse(self) -> None:
        city = build_city(n=16, seed=4)
        s, t = city.intersections[0], city.intersections[-1]
        routes = generate_candidates(city.graph, s, t, city.historical, 8 * 3600)
        evals = [evaluate(r, city.historical, 8 * 3600) for r in routes]
        picks = select_routes(evals, MODES["balanced"], k=5, max_overlap=0.7)
        self.assertGreaterEqual(len(picks), 3)
        fastest_key = min(evals, key=lambda ev: ev.arrival).route.key
        for i, a in enumerate(picks):
            for b in picks[i + 1 :]:
                exempt = {a.evaluation.route.key, b.evaluation.route.key} & {fastest_key, picks[0].evaluation.route.key}
                if len(exempt) < 2:
                    self.assertLessEqual(overlap(a.evaluation.route.edges, b.evaluation.route.edges), 0.7)

    def test_overlap(self) -> None:
        route = next(ev.route for ev in self.evals)
        self.assertAlmostEqual(overlap(route.edges, route.edges), 1.0)
        other = next(ev.route for ev in self.evals if not set(ev.route.key) & set(route.key))
        self.assertEqual(overlap(route.edges, other.edges), 0.0)

    def test_route_attributes(self) -> None:
        motorway = next(ev for ev in self.evals if ev.toll_krw)
        self.assertEqual(motorway.toll_krw, 1_200)
        self.assertGreater(motorway.highway_share, 0.9)
        self.assertEqual(Route((), frozenset()).length_m, 0)


class BacktestTest(unittest.TestCase):
    def test_runs_and_reports_sane_metrics(self) -> None:
        results = run_backtest(days=1, trips_per_day=4, seed=3)
        self.assertEqual(len(results), 4)
        for result in results:
            self.assertEqual(len(result.actual_s), 4)
            summary = result.summary()
            self.assertGreaterEqual(summary["regret_min"], -1e-9)
            self.assertGreaterEqual(summary["pool_regret_min"], -1e-9)
            self.assertLessEqual(summary["pool_regret_min"], summary["regret_min"] + 1e-9)
            self.assertTrue(0 <= summary["hit_rate_pct"] <= 100)


if __name__ == "__main__":
    unittest.main()
