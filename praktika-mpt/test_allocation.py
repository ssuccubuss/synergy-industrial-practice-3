import unittest

from allocation import assign


def students(profiles):
    return [{"id": key, "profile": profile} for key, profile in enumerate(profiles, 1)]


def places(items):
    return [{"id": key, "profile": profile, "capacity": capacity}
            for key, (profile, capacity) in enumerate(items, 1)]


def preferences(*items):
    return [{"student_id": student, "place_id": place, "rank": rank}
            for student, place, rank in items]


class AllocationTests(unittest.TestCase):
    def test_moves_first_student_to_second_choice_to_increase_coverage(self):
        result = assign(
            students(["web", "web"]), places([("web", 1), ("web", 1)]),
            preferences((1, 1, 1), (1, 2, 2), (2, 1, 1)), set(),
        )
        self.assertEqual(result, {1: (2, 2), 2: (1, 1)})

    def test_student_priority_precedes_partner_interest(self):
        result = assign(
            students(["web"]), places([("web", 1), ("web", 1)]),
            preferences((1, 1, 1), (1, 2, 2)), {(1, 2)},
        )
        self.assertEqual(result, {1: (1, 1)})

    def test_interest_breaks_tie_at_capacity(self):
        result = assign(
            students(["web", "web", "web"]), places([("web", 2)]),
            preferences((1, 1, 1), (2, 1, 1), (3, 1, 1)), {(3, 1)},
        )
        self.assertIn(3, result)
        self.assertEqual(len(result), 2)

    def test_wrong_profile_and_missing_preferences_have_no_assignment(self):
        result = assign(
            students(["web", "web"]), places([("net", 4)]),
            preferences((1, 1, 1)), set(),
        )
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()

