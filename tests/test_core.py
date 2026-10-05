from app.core import grid_points, normalize_phone, score

def test_grid():
    assert len(grid_points(16.2,-61.5,1000,1)) == 9

def test_phone():
    assert normalize_phone("+590690123456") == "590690123456"

def test_score():
    assert score(0,None,"+590690123456") == 5
