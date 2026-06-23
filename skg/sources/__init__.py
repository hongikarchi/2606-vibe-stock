"""Real-data source fetchers (the ingest swap seam, productionized).

`edgar` is key-free and runs today; `dart` is a stub that activates when the user
pastes a free OpenDART key into cfg.DART_API_KEY. Both emit the same shapes the offline
pipeline already consumes: issuer_master tuples + corpus Document dicts.
"""
