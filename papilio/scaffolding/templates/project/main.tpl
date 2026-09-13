<<IMPORTS>>


def build_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else get_settings()
<<CHECKS>>
    providers = [
<<PROVIDERS>>
    ]
    return create_app(settings, providers=providers)


app = build_app()
