"""Token de sessão do oráculo (ADR-0018): aleatório no cookie, só o hash no banco."""

from src.support.utils.session_tokens import generate_session_token, hash_session_token


def test_token_gerado_e_aleatorio_e_longo():
    a, b = generate_session_token(), generate_session_token()
    assert a != b
    assert len(a) >= 40  # 32 bytes urlsafe ≈ 43 chars


def test_hash_e_sha256_hex_deterministico():
    assert hash_session_token("abc") == hash_session_token("abc")
    assert hash_session_token("abc") != hash_session_token("abd")
    assert len(hash_session_token("abc")) == 64
    assert hash_session_token("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
