"""Comparação de nomes e nomes de arquivo dos certificados.

Os nomes são comparados sem acento, sem maiúsculas, sem espaços repetidos e
sem as preposições (da, de, do, dos, das, e): "Joao Carlos Silva" acha
"João Carlos da Silva".
"""

from __future__ import annotations

import re
import unicodedata

PARTICULAS = {"da", "de", "do", "das", "dos", "e", "d"}


def sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto or "") if unicodedata.category(c) != "Mn")


def normalizar(nome: str) -> str:
    texto = re.sub(r"[^\w\s]", " ", sem_acento(nome or "").lower())
    return re.sub(r"\s+", " ", texto).strip()


def palavras(nome: str) -> list[str]:
    """As palavras do nome que contam (sem preposições)."""
    return [p for p in normalizar(nome).split() if p not in PARTICULAS]


def mesmo_nome(procurado: str, achado: str) -> bool:
    """Nome igual (sem acento/caixa/preposições), ou o achado tem todas as
    palavras do procurado, na mesma ordem (ex.: "Bruno Oliveira" acha
    "Bruno Matias Goncalo de Oliveira"). Exige 2 palavras ou mais."""
    p, a = palavras(procurado), palavras(achado)
    if not p or not a:
        return False
    if p == a:
        return True
    if len(p) < 2 or p[0] != a[0]:
        return False
    resto = iter(a)
    return all(any(x == y for y in resto) for x in p)


def nomes_colados(texto: str) -> list[str]:
    """Um nome por linha (também aceita ; e tabulação), sem repetidos e sem números soltos."""
    nomes, vistos = [], set()
    for parte in re.split(r"[\n;\t]+", texto or ""):
        nome = re.sub(r"^\s*\d+\s*[-.)]?\s*", "", parte).strip(" ,")  # "1. Maria" / "1 - Maria"
        chave = " ".join(palavras(nome))
        if chave and chave not in vistos:
            vistos.add(chave)
            nomes.append(re.sub(r"\s+", " ", nome))
    return nomes


def ler_progresso(texto: str) -> float | None:
    numero = re.search(r"\d+(?:[.,]\d+)?", str(texto or ""))
    if not numero:
        return None
    return float(numero.group().replace(",", "."))


def nome_certificado(aluno: str, curso: str) -> str:
    """'Nome - Curso.pdf', sem caracteres que o Windows não aceita em nome de arquivo."""
    aluno = " ".join(p if p in PARTICULAS else p.capitalize() for p in aluno.lower().split())
    nome = f"{aluno} - {curso.strip()}"
    nome = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", nome)
    nome = re.sub(r"\s+", " ", nome).strip(" .")
    return nome[:150] + ".pdf"
