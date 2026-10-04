from firstlook.terminology.router import preferred_language


def test_accept_language_prefers_highest_supported_quality() -> None:
    assert preferred_language("it-IT,it;q=0.8,pl-PL;q=0.9,en;q=0.5") == "it"
    assert preferred_language("de-DE,pl-PL;q=0.9,en;q=0.5") == "pl"
    assert preferred_language("de-DE,fr;q=0.9") == "en"
    assert preferred_language("pl;q=0,it;q=0.8") == "it"
