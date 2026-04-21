import unittest

from backend.admission_profiles import (
    _infer_route_details_for_row,
    answer_admission_question,
    resolve_program_admission,
)
from tests.backend_fixtures import build_test_admission_profiles, build_test_kg


class AdmissionProfileAnswerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kg = build_test_kg()
        cls.program_profiles = build_test_admission_profiles()

    def test_generic_btech_fee_query_returns_grouped_examples(self):
        profiles = {
            "admission--india--engineering": {
                "route": "india",
                "source_url": "https://www.srmist.edu.in/admission-india/engineering/",
                "last_scraped_at": "2026-04-12",
                "program_rows": [
                    {
                        "campus": "KTR",
                        "degree": "B.Tech",
                        "specialization": "Electrical and Electronics Engineering",
                        "annual_fees": "275000",
                        "program_type": "Full Time",
                        "source_url": "https://www.srmist.edu.in/admission-india/engineering/",
                    },
                    {
                        "campus": "KTR",
                        "degree": "B.Tech",
                        "specialization": "Mechanical Engineering",
                        "annual_fees": "275000",
                        "program_type": "Full Time",
                        "source_url": "https://www.srmist.edu.in/admission-india/engineering/",
                    },
                    {
                        "campus": "KTR",
                        "degree": "B.Tech",
                        "specialization": "Aeronautical Engineering",
                        "annual_fees": "400000",
                        "program_type": "Full Time",
                        "source_url": "https://www.srmist.edu.in/admission-india/engineering/",
                    },
                    {
                        "campus": "KTR",
                        "degree": "B.Tech",
                        "specialization": "Computer Science and Engineering",
                        "annual_fees": "475000",
                        "program_type": "Full Time",
                        "source_url": "https://www.srmist.edu.in/admission-india/engineering/",
                    },
                    {
                        "campus": "KTR",
                        "degree": "B.Tech",
                        "specialization": "Mechanical Engineering (Flexible Timings)",
                        "annual_fees": "100000",
                        "program_type": "Part Time",
                        "source_url": "https://www.srmist.edu.in/admission-india/engineering/",
                    },
                ],
            }
        }

        result = answer_admission_question(
            "What are the B.Tech fees?",
            campus="KTR",
            kg=self.kg,
            profiles=profiles,
        )

        self.assertIsNotNone(result)
        answer = result["answer"]
        self.assertIn("B.Tech fees at KTR are not uniform", answer)
        self.assertIn("INR 2,75,000 per year", answer)
        self.assertIn("INR 4,00,000 per year", answer)
        self.assertIn("INR 4,75,000 per year", answer)
        self.assertIn("INR 1,00,000 per year", answer)
        self.assertIn("Treat a fee as annual only", answer)

    def test_generic_mtech_fee_query_keeps_entire_programme_separate(self):
        profiles = {
            "admission--india--engineering": {
                "route": "india",
                "source_url": "https://www.srmist.edu.in/admission-india/engineering/",
                "last_scraped_at": "2026-04-12",
                "program_rows": [
                    {
                        "campus": "KTR",
                        "degree": "M.Tech",
                        "specialization": "Computer Science and Engineering",
                        "annual_fees": "160000",
                        "program_type": "Full Time",
                        "source_url": "https://www.srmist.edu.in/admission-india/engineering/",
                    },
                    {
                        "campus": "KTR",
                        "degree": "M.Tech",
                        "specialization": "Data Science",
                        "annual_fees": "160000",
                        "program_type": "Full Time",
                        "source_url": "https://www.srmist.edu.in/admission-india/engineering/",
                    },
                    {
                        "campus": "KTR",
                        "degree": "M.Tech",
                        "specialization": "Artificial Intelligence (Flexible Timings)",
                        "annual_fees": "5,00,000 (for the entire programme)",
                        "program_type": "Part Time",
                        "source_url": "https://www.srmist.edu.in/admission-india/engineering/",
                    },
                ],
            }
        }

        result = answer_admission_question(
            "What are the M.Tech fees?",
            campus="KTR",
            kg=self.kg,
            profiles=profiles,
        )

        self.assertIsNotNone(result)
        answer = result["answer"]
        self.assertIn("INR 1,60,000 per year", answer)
        self.assertIn("INR 5,00,000 for the entire programme", answer)
        self.assertNotIn("INR 5,00,000 per year", answer)

    def test_btech_aiml_admission_uses_srmjeee_override_and_filters_invalid_steps(self):
        result = answer_admission_question(
            "How to get admission in BTECH AIML",
            campus="KTR",
            kg=self.kg,
            profiles=self.program_profiles,
        )

        self.assertIsNotNone(result)
        answer = result["answer"]
        resolution = result["admission_resolution"]

        self.assertIn("SRMJEEE (UG)", answer)
        self.assertIn("https://applications.srmist.edu.in/btech", answer)
        self.assertEqual(resolution["route_family"], "srmjeee_ug")
        self.assertTrue(resolution["override_used"])
        for blocked in ("SMAT", "CET", "PI", "GD", "Round 1", "Round 2"):
            self.assertNotIn(blocked, answer)

    def test_bsc_nursing_admission_uses_srmjeeh_override(self):
        result = answer_admission_question(
            "How to get admission in BSc Nursing",
            campus="KTR",
            kg=self.kg,
            profiles=self.program_profiles,
        )

        self.assertIsNotNone(result)
        answer = result["answer"]
        resolution = result["admission_resolution"]

        self.assertIn("SRMJEEH UG", answer)
        self.assertIn("https://applications.srmist.edu.in/srmhs", answer)
        self.assertEqual(resolution["route_family"], "srmjeeh_ug")
        self.assertTrue(resolution["override_used"])
        self.assertNotIn("CET", answer)
        self.assertNotIn("Post Basic Diploma", answer)
        self.assertNotIn("Operation Room Nursing", answer)

    def test_bpharm_admission_uses_srmjeeh_override(self):
        result = answer_admission_question(
            "How to get admission in BPharm",
            campus="KTR",
            kg=self.kg,
            profiles=self.program_profiles,
        )

        self.assertIsNotNone(result)
        answer = result["answer"]
        resolution = result["admission_resolution"]

        self.assertIn("SRMJEEH UG", answer)
        self.assertIn("https://applications.srmist.edu.in/srmhs", answer)
        self.assertEqual(resolution["route_family"], "srmjeeh_ug")
        self.assertTrue(resolution["override_used"])
        self.assertNotIn("CET", answer)
        self.assertNotIn("Post Basic Diploma", answer)

    def test_conflicting_health_science_tokens_are_marked_conflict(self):
        route_details = _infer_route_details_for_row(
            {
                "degree": "B.Pharm",
                "specialization": "Pharmacy",
                "dept": "Pharmacy",
                "program_level": "Under Graduate",
                "program_type": "Full Time",
            },
            criteria_text="Admissions are routed through SRMJEEN - UG for some summaries.",
            how_to_apply_text="The application portal calls this SRMJEEH UG.",
            source_url="https://www.srmist.edu.in/admission-india/medicine-health-sciences/",
        )

        self.assertEqual(route_details["verification_status"], "conflict")
        self.assertEqual(route_details["route_family"], "srmjeeh_ug")
        self.assertIn("srmjeeh_ug", route_details["raw_route_tokens"])
        self.assertIn("srmjeen_ug", route_details["raw_route_tokens"])

    def test_conflict_profile_uses_override_resolution(self):
        resolution = resolve_program_admission(
            "program--b-pharm-pharmacy",
            campus="KTR",
            kg=self.kg,
            profiles=self.program_profiles,
        )

        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.route_family, "srmjeeh_ug")
        self.assertEqual(resolution.exam_name, "SRMJEEH UG")
        self.assertEqual(resolution.application_url, "https://applications.srmist.edu.in/srmhs")
        self.assertEqual(resolution.verification_status, "override")
        self.assertTrue(resolution.override_used)

    def test_engineering_btech_rows_map_to_srmjeee_ug(self):
        route_details = _infer_route_details_for_row(
            {
                "degree": "B.Tech",
                "specialization": "Computer Science and Engineering with specialization in Artificial Intelligence and Machine Learning",
                "dept": "Computer Science and Engineering",
                "program_level": "Under Graduate",
                "program_type": "Full Time",
            },
            criteria_text="Admissions are through SRMJEEE (UG).",
            how_to_apply_text="Apply through the official engineering admission portal.",
            source_url="https://www.srmist.edu.in/admission-india/engineering/",
        )

        self.assertEqual(route_details["route_family"], "srmjeee_ug")
        self.assertEqual(route_details["verification_status"], "verified")
        self.assertEqual(route_details["exam_name"], "SRMJEEE (UG)")

    def test_unresolved_program_falls_back_with_explicit_uncertainty(self):
        result = answer_admission_question(
            "How to get admission in BTech Quantum Robotics in engineering?",
            campus="KTR",
            kg=self.kg,
            profiles=self.program_profiles,
        )

        self.assertIsNotNone(result)
        self.assertIn("I could not confidently resolve the exact program", result["answer"])
        self.assertIn("Admissions - India - Engineering", result["answer"])


if __name__ == "__main__":
    unittest.main()
