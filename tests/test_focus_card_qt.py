"""A real Qt construction catches PyQt-only keyword arguments after migration."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from core.galaxy_card import Card


def test_focus_card_constructs_with_pyside6(monkeypatch):
    app=QApplication.instance() or QApplication([])
    # No service or private focus session is needed to validate widget creation.
    monkeypatch.setattr('threading.Thread.start',lambda _:None)
    card=Card(1)
    assert card.width()>0 and card.height()>0
    card.stop.set();card.close();card.deleteLater();app.processEvents()
