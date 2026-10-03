"""Failed default-request gates must leave experimental kernels opt-in."""
from cube_app.solvers.qtm import native


def test_qtm_uses_generic_unless_explicitly_requested(monkeypatch):
    monkeypatch.delenv("CUBE_QTM_EXPANSION", raising=False)
    assert "--qtm-expansion=generic" in native._PersistentNativeSolver()._command()
    monkeypatch.setenv("CUBE_QTM_EXPANSION", "full-strong")
    assert "--qtm-expansion=full-strong" in native._PersistentNativeSolver()._command()
