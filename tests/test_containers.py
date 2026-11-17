from __future__ import annotations

import json
import unittest

from labcheck.checks import containers
from labcheck.config import Config, DockerConfig
from tests.helpers import FakeRunner, LabcheckTestCase, response


def line(name: str, state: str, status: str) -> str:
    return json.dumps({"Names": name, "State": state, "Status": status})


PS = "docker ps -a --format {{json .}}"


class ContainersCheckTest(LabcheckTestCase):
    def runner(
        self, stdout: str = "", returncode: int = 0, stderr: str = ""
    ) -> FakeRunner:
        return FakeRunner(
            available=["docker"], responses={PS: response(stdout, returncode, stderr)}
        )

    def test_missing_docker_is_skipped(self) -> None:
        result = containers.run(self.context())
        self.assertEqual(result.status.value, "skip")
        self.assertIn("not installed", result.summary)

    def test_running_containers_are_ok(self) -> None:
        runner = self.runner(
            line("traefik", "running", "Up 2 days")
            + "\n"
            + line("nextcloud", "running", "Up 2 days (healthy)")
        )
        result = containers.run(self.context(runner=runner))
        self.assertEqual(result.status.value, "ok")
        self.assertEqual(result.summary, "2 running")
        metrics = {metric.name: metric.value for metric in result.metrics}
        self.assertEqual(metrics["containers_total"], 2)
        self.assertEqual(metrics["containers_running"], 2)
        self.assertEqual(metrics["containers_unhealthy"], 0)

    def test_stopped_container_is_a_warning(self) -> None:
        runner = self.runner(line("old", "exited", "Exited (0) 3 hours ago"))
        result = containers.run(self.context(runner=runner))
        self.assertEqual(result.status.value, "warn")
        self.assertEqual(result.summary, "0 running, 1 stopped")
        self.assertIn("old: exited", "\n".join(result.details))

    def test_unhealthy_container_is_critical(self) -> None:
        runner = self.runner(line("web", "running", "Up 5 minutes (unhealthy)"))
        result = containers.run(self.context(runner=runner))
        self.assertEqual(result.status.value, "crit")
        self.assertIn("1 unhealthy: web", result.summary)
        self.assertIn("web: unhealthy", "\n".join(result.details))

    def test_restarting_container_is_critical(self) -> None:
        runner = self.runner(line("web", "restarting", "Restarting (1) 5 seconds ago"))
        result = containers.run(self.context(runner=runner))
        self.assertEqual(result.status.value, "crit")
        self.assertIn("web", result.summary)

    def test_paused_container_is_a_warning(self) -> None:
        runner = self.runner(line("web", "paused", "Up 5 minutes (Paused)"))
        result = containers.run(self.context(runner=runner))
        self.assertEqual(result.status.value, "warn")

    def test_ignore_patterns(self) -> None:
        runner = self.runner(
            line("watchtower", "exited", "Exited (0) 1 hour ago")
            + "\n"
            + line("web", "running", "Up 5 minutes")
        )
        config = Config(docker=DockerConfig(ignore=["watchtower"]))
        result = containers.run(self.context(config=config, runner=runner))
        self.assertEqual(result.status.value, "ok")
        self.assertEqual(result.summary, "1 running")

    def test_ignore_matches_any_alias(self) -> None:
        runner = self.runner(line("web,alias", "running", "Up 5 minutes"))
        config = Config(docker=DockerConfig(ignore=["alias"]))
        result = containers.run(self.context(config=config, runner=runner))
        self.assertEqual(result.status.value, "ok")
        self.assertEqual(result.summary, "no containers")

    def test_require_running_success(self) -> None:
        runner = self.runner(
            line("traefik", "running", "Up 2 days")
            + "\n"
            + line("db", "running", "Up 2 days")
        )
        config = Config(docker=DockerConfig(require_running=["traefik", "db"]))
        result = containers.run(self.context(config=config, runner=runner))
        self.assertEqual(result.status.value, "ok")

    def test_required_container_missing(self) -> None:
        runner = self.runner(line("web", "running", "Up 2 days"))
        config = Config(docker=DockerConfig(require_running=["traefik"]))
        result = containers.run(self.context(config=config, runner=runner))
        self.assertEqual(result.status.value, "crit")
        self.assertIn("required missing: traefik", result.summary)
        self.assertIn(
            "required container 'traefik' was not found", "\n".join(result.details)
        )

    def test_required_container_present_but_stopped(self) -> None:
        runner = self.runner(line("traefik", "exited", "Exited (1) 1 hour ago"))
        config = Config(docker=DockerConfig(require_running=["traefik"]))
        result = containers.run(self.context(config=config, runner=runner))
        self.assertEqual(result.status.value, "crit")
        self.assertIn(
            "required container 'traefik' is not running",
            "\n".join(result.details),
        )

    def test_daemon_unreachable_is_critical(self) -> None:
        runner = self.runner(
            returncode=1,
            stderr=(
                "Cannot connect to the Docker daemon at "
                "unix:///var/run/docker.sock. Is the docker daemon running?"
            ),
        )
        result = containers.run(self.context(runner=runner))
        self.assertEqual(result.status.value, "crit")
        self.assertIn("daemon unreachable", result.summary)

    def test_other_docker_failure_is_an_error(self) -> None:
        runner = self.runner(returncode=1, stderr="permission denied")
        result = containers.run(self.context(runner=runner))
        self.assertEqual(result.status.value, "error")
        self.assertIn("docker ps failed", result.summary)

    def test_malformed_json_is_an_error(self) -> None:
        runner = self.runner("not json\n")
        result = containers.run(self.context(runner=runner))
        self.assertEqual(result.status.value, "error")
        self.assertIn("cannot parse", result.summary)

    def test_no_containers(self) -> None:
        result = containers.run(self.context(runner=self.runner("")))
        self.assertEqual(result.status.value, "ok")
        self.assertEqual(result.summary, "no containers")


if __name__ == "__main__":
    unittest.main()
