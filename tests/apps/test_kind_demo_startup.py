import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_demo_refreshes_existing_pods_before_starting_probes(tmp_path: Path):
    # Exercise the real lifecycle commands without creating Kubernetes resources.
    script = (ROOT / "demo/kind/up.sh").read_text(encoding="utf-8")
    start = script.index('kubectl --context "${KUBECTL_CONTEXT}" delete -f ')
    end = script.index("SERVER_WORKLOADS=", start)
    lifecycle = script[start:end]
    examples = tmp_path / "examples"
    examples.mkdir()
    (examples / "profile-tcp.yaml").touch()
    (examples / "measurement-tcp-probe.yaml").touch()

    # Model an operator that starts a probe as soon as its measurement exists.
    # Deleting its client or server Pod during this run fails the measurement.
    kubectl_stub = r"""
kubectl() {
  case " $* " in
    *" apply -f "*"measurement-tcp-probe.yaml "*)
      touch "${DEMO_TMP_DIR}/probe-started"
      ;;
    *" get pod "*)
      echo pod/existing-server
      if [[ -f "${DEMO_TMP_DIR}/probe-started" ]]; then
        echo pod/probe-server
        echo pod/probe-client
      fi
      ;;
    *" delete "*"pod/"*)
      touch "${DEMO_TMP_DIR}/existing-refreshed"
      if [[ "$*" == *pod/probe-* ]]; then
        touch "${DEMO_TMP_DIR}/probe-interrupted"
      fi
      ;;
  esac
  return 0
}
"""
    subprocess.run(
        ["bash", "-euo", "pipefail", "-c", kubectl_stub + lifecycle],
        env={
            **os.environ,
            "DEMO_TMP_DIR": str(tmp_path),
            "KUBECTL_CONTEXT": "kind-test",
            "NAMESPACE": "test",
        },
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert (tmp_path / "existing-refreshed").exists()
    assert (tmp_path / "probe-started").exists()
    assert not (tmp_path / "probe-interrupted").exists()
