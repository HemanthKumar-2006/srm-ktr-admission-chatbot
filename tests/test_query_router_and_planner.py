import unittest

from backend.answer_planner import build_answer_plan
from backend.query_router import route_query
from tests.backend_fixtures import build_test_kg


class QueryRouterAndPlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kg = build_test_kg()

    def test_role_query_routes_to_kg_role_with_department(self):
        route = route_query("Who is the HOD of CSE?", selected_campus="KTR", kg=self.kg)

        self.assertEqual(route.domain, "faculty")
        self.assertEqual(route.task, "lookup")
        self.assertEqual(route.routing_target, "kg_role")
        self.assertEqual(route.entities["department"], "Computer Science and Engineering")

    def test_listing_query_builds_candidate_items(self):
        route = route_query(
            "What departments are under Faculty of Engineering and Technology?",
            selected_campus="KTR",
            kg=self.kg,
        )
        plan = build_answer_plan(
            "What departments are under Faculty of Engineering and Technology?",
            route,
            kg=self.kg,
        )

        self.assertEqual(route.domain, "departments")
        self.assertEqual(route.task, "list")
        self.assertEqual(route.routing_target, "kg_listing")
        self.assertIn("Faculty of Engineering & Technology", route.entities["college"])
        self.assertIn("Computer Science and Engineering", plan.candidate_items)
        self.assertIn("Electronics and Communication Engineering", plan.candidate_items)

    def test_compare_query_decomposes_two_programs(self):
        question = "Compare B.Tech CSE and AI&ML admissions, fees, and eligibility for Ramapuram."
        route = route_query(question, selected_campus="KTR", kg=self.kg)
        plan = build_answer_plan(question, route, kg=self.kg)

        self.assertEqual(route.domain, "admissions")
        self.assertEqual(route.task, "compare")
        self.assertEqual(route.routing_target, "comparison")
        self.assertTrue(route.needs_decomposition)
        self.assertEqual(route.entities["campus"], "Ramapuram")
        self.assertEqual(
            route.entities["programs"],
            [
                "B.Tech Computer Science Engineering 2026",
                "B.Tech CSE AI and Machine Learning 2026",
            ],
        )
        self.assertEqual(plan.response_shape, "comparison")
        self.assertEqual(plan.comparison_axes, ["admission_route", "fees", "eligibility"])
        self.assertEqual(len(plan.decomposition_steps), 3)

    def test_generic_mba_query_does_not_force_specific_program(self):
        route = route_query("How do I apply for MBA at SRM?", selected_campus="KTR", kg=self.kg)
        plan = build_answer_plan("How do I apply for MBA at SRM?", route, kg=self.kg)

        self.assertEqual(route.domain, "admissions")
        self.assertEqual(route.task, "procedure")
        self.assertNotIn("program", route.entities)
        self.assertIn("specific program or faculty scope", plan.missing_info)

    def test_pinned_program_context_is_used_for_ambiguous_query(self):
        route = route_query(
            "What is the fee structure?",
            selected_campus="KTR",
            kg=self.kg,
            pinned_context={
                "type": "program",
                "value": "B.Tech Computer Science Engineering 2026",
                "entity_id": "program--b-tech-computer-science-and-engineering",
            },
        )

        self.assertTrue(route.used_pinned_context)
        self.assertEqual(route.entities["program"], "B.Tech Computer Science Engineering 2026")
        self.assertEqual(route.routing_target, "admissions")

    def test_explicit_campus_overrides_pinned_campus(self):
        route = route_query(
            "Compare B.Tech CSE and AI&ML for Ramapuram",
            selected_campus="KTR",
            kg=self.kg,
            pinned_context={"type": "campus", "value": "Delhi-NCR"},
        )

        self.assertEqual(route.entities["campus"], "Ramapuram")
        self.assertFalse(route.used_pinned_context)


if __name__ == "__main__":
    unittest.main()
