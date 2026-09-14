<<IMPORTS>>


def build_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else get_settings()
<<CHECKS>>
    providers = [
<<PROVIDERS>>
    ]
<<LIFESPAN>>
<<MIDDLEWARE>>
    return create_app(settings, providers=providers<<LIFESPAN_ARG>>)


app = build_app()
