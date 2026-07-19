import unittest
from pathlib import Path


class LaunchScriptTests(unittest.TestCase):
    def test_launcher_bootstraps_and_invokes_pip_through_venv_python(self):
        launch = Path("launch.bat").read_text(encoding="utf-8")

        self.assertNotIn(r"venv\Scripts\pip.exe", launch)
        self.assertIn(r"venv\Scripts\python.exe -m pip --version", launch)
        self.assertIn(r"venv\Scripts\python.exe -m ensurepip --upgrade", launch)
        self.assertIn(r"venv\Scripts\python.exe -m pip install -r requirements.txt", launch)


if __name__ == "__main__":
    unittest.main()
