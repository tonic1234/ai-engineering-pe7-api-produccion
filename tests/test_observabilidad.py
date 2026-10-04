"""Tests de la instrumentación (25% de la rúbrica).

No levantan Phoenix: verifican que la instrumentación se active sólo cuando hay configuración
y que, si no la hay, lo diga en voz alta en vez de quedarse en silencio (la devolución de la
pre-entrega 4 pidió justamente no degradar en silencio).
"""

from __future__ import annotations

from app.observabilidad import activar_trazas, endpoint_configurado, trazas_activas


def test_sin_endpoint_no_activa_nada(monkeypatch):
    monkeypatch.delenv("PHOENIX_COLLECTOR_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert endpoint_configurado() is False
    assert activar_trazas() is False
    assert trazas_activas() is False


def test_sin_endpoint_avisa_por_log(monkeypatch, caplog):
    monkeypatch.delenv("PHOENIX_COLLECTOR_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    with caplog.at_level("WARNING"):
        activar_trazas()
    assert any("traza" in r.message.lower() or "phoenix" in r.message.lower() for r in caplog.records)


def test_con_endpoint_configurado_se_activa(monkeypatch):
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://127.0.0.1:6006/v1/traces")
    monkeypatch.setenv("PHOENIX_PROJECT_NAME", "pre-entrega-7")
    assert endpoint_configurado() is True
    assert activar_trazas() is True
    assert trazas_activas() is True


def test_el_nombre_del_proyecto_es_el_de_la_variable(monkeypatch):
    monkeypatch.setenv("PHOENIX_PROJECT_NAME", "pe7-pruebas")
    from app.observabilidad import nombre_proyecto

    assert nombre_proyecto() == "pe7-pruebas"


def test_el_nombre_del_proyecto_tiene_default(monkeypatch):
    monkeypatch.delenv("PHOENIX_PROJECT_NAME", raising=False)
    from app.observabilidad import nombre_proyecto

    assert nombre_proyecto()
