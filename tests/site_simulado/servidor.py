"""Servidor do site simulado: devolve o index.html para todas as rotas (como a
plataforma, que é uma página única) e um PDF de exemplo em /api/certificado/."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PAGINA = (Path(__file__).parent / "index.html").read_bytes()


def pdf_exemplo(texto: str) -> bytes:
    conteudo = f"BT /F1 18 Tf 50 750 Td ({texto}) Tj ET".encode()
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 595] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(conteudo) + conteudo + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    saida, posicoes = b"%PDF-1.4\n", []
    for n, obj in enumerate(objetos, 1):
        posicoes.append(len(saida))
        saida += b"%d 0 obj\n" % n + obj + b"\nendobj\n"
    xref = len(saida)
    saida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1)
    saida += b"".join(b"%010d 00000 n \n" % p for p in posicoes)
    saida += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objetos) + 1, xref)
    return saida


class Pagina(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/api/certificado/"):
            corpo, tipo = pdf_exemplo("Certificado " + self.path.rsplit("/", 1)[-1]), "application/pdf"
        else:
            corpo, tipo = PAGINA, "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *_):
        pass


def iniciar(porta: int = 0) -> tuple[ThreadingHTTPServer, str]:
    servidor = ThreadingHTTPServer(("127.0.0.1", porta), Pagina)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return servidor, f"http://127.0.0.1:{servidor.server_address[1]}"


if __name__ == "__main__":
    s, url = iniciar(8765)
    print(f"Site simulado em {url}/login (CPF 456.456.456-00, senha teste). Ctrl+C para sair.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        s.shutdown()
