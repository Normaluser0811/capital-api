"""pytest 設定本身的守衛（設定被拿掉時，其他測試不會發現）。"""


def test_every_xfail_is_strict(pytestconfig):
    """pyproject 的 xfail_strict 必須是 true：已知缺陷其實修好了（XPASS）就要轉紅，逼人拿掉標記。

    2026-11-19 覆核：沒有這項時，把 xfail 以非 strict 形式加回去，全套照樣綠（120 passed, 1 xpassed）；
    只靠 pyproject 那一行也不夠——把那一行拿掉，全套同樣照綠（突變 M7）。
    """
    assert pytestconfig.getini("xfail_strict") is True
