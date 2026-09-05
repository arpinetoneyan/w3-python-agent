import unittest

from src.solver import ProgrammaticSolver


class ProgrammaticSolverTests(unittest.TestCase):
    def test_extract_one_blank(self) -> None:
        self.assertEqual(
            ProgrammaticSolver._extract_blanks('@(5)("Hello World")', 'print("Hello World")'),
            ["print"],
        )

    def test_extract_multiple_blanks(self) -> None:
        self.assertEqual(
            ProgrammaticSolver._extract_blanks("x = @(1)\ny = @(1)", "x = 5\ny = 7"),
            ["5", "7"],
        )

    def test_extract_with_flexible_whitespace(self) -> None:
        self.assertEqual(
            ProgrammaticSolver._extract_blanks("if @(4):\n  print(x)", "if True:\n    print(x)"),
            ["True"],
        )


if __name__ == "__main__":
    unittest.main()
