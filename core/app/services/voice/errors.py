class VoiceError(Exception):
    def __init__(self, code: str, status: int = 422):
        self.code, self.status = code, status
        super().__init__(code)
