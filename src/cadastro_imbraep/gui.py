"""Tela do app: cola os colaboradores (CPF e nome), confere e cadastra."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__, credenciais
from .config import pasta_certificados
from .entrada import Colaborador, ler_lista
from .nomes import nome_certificado, nomes_colados, normalizar

SITUACOES = {
    "cadastrado": ("cadastrado", "ok"),
    "vinculado": ("vinculado à empresa", "ok"),
    "ja_cadastrado": ("já cadastrado (pulado)", "aviso"),
    "arquivado": ("arquivado (pulado)", "aviso"),
    "teste": ("modo teste", ""),
    "erro": ("erro", "erro"),
}


def detalhe_do_erro(erro: Exception) -> str:
    """A mensagem do Selenium traz um stacktrace sem utilidade; fica só a 1ª linha."""
    linhas = (getattr(erro, "msg", None) or str(erro)).strip().splitlines()
    return f"{type(erro).__name__}: {linhas[0] if linhas else 'sem detalhes'}"


def abrir_pasta(pasta: Path):
    if sys.platform == "win32":
        os.startfile(pasta)  # noqa: S606
    else:
        subprocess.Popen(["xdg-open", str(pasta)])


class Registro(tk.Text):
    def __init__(self, pai, **kw):
        super().__init__(pai, state="disabled", wrap="word", **kw)

    def escrever(self, texto: str):
        self.config(state="normal")
        self.insert("end", f"{datetime.now():%H:%M:%S}  {texto}\n")
        self.see("end")
        self.config(state="disabled")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Cadastro Imbraep {__version__}")
        self.geometry("1000x680")
        self.minsize(860, 560)
        self.colaboradores: list[Colaborador] = []
        self.fila: queue.Queue = queue.Queue()
        self.enviando = False
        self.modo_teste = tk.BooleanVar(value=False)
        self.mostrar_navegador = tk.BooleanVar(value=False)
        self._montar_tela()
        self.after(200, self._processar_fila)

    # ---------- montagem ----------
    def _montar_tela(self):
        topo = ttk.Frame(self, padding=8)
        topo.pack(fill="x")
        ttk.Label(topo, text="Colaboradores: CPF e nome completo, um por linha (pode colar vários de uma vez), "
                             "ou abra as fichas em PDF.").pack(side="left")
        ttk.Button(topo, text="Monitoramento", command=lambda: JanelaMonitoramento(self)).pack(side="right")

        self.txt = tk.Text(self, height=8, wrap="none")
        self.txt.pack(fill="x", padx=8)
        self.txt.insert("1.0", "")
        botoes = ttk.Frame(self, padding=(8, 6))
        botoes.pack(fill="x")
        ttk.Button(botoes, text="Abrir fichas (PDF)...", command=self.abrir_fichas).pack(side="left")
        ttk.Button(botoes, text="Conferir lista", command=self.conferir).pack(side="left", padx=6)
        ttk.Button(botoes, text="Limpar", command=self.limpar).pack(side="left", padx=6)
        self.lbl_total = ttk.Label(botoes, text="")
        self.lbl_total.pack(side="left", padx=10)

        colunas = ("nome", "cpf", "situacao")
        self.tabela = ttk.Treeview(self, columns=colunas, show="headings")
        for col, titulo, largura in [("nome", "Nome completo", 300), ("cpf", "CPF", 130),
                                     ("situacao", "Situação", 460)]:
            self.tabela.heading(col, text=titulo)
            self.tabela.column(col, width=largura, anchor="w")
        self.tabela.tag_configure("ok", foreground="#15803d")
        self.tabela.tag_configure("aviso", foreground="#b45309")
        self.tabela.tag_configure("erro", foreground="#b91c1c")
        self.tabela.pack(fill="both", expand=True, padx=8)

        rodape = ttk.Frame(self, padding=8)
        rodape.pack(fill="x")
        self.btn_cadastrar = ttk.Button(rodape, text="Cadastrar na plataforma", command=self.cadastrar)
        self.btn_cadastrar.pack(side="right")
        ttk.Checkbutton(rodape, text="Mostrar navegador", variable=self.mostrar_navegador).pack(side="right", padx=8)
        ttk.Checkbutton(rodape, text="Modo teste (não salva)", variable=self.modo_teste).pack(side="right", padx=8)
        ttk.Button(rodape, text="Esquecer login salvo", command=self.esquecer_login).pack(side="left")

        self.log = Registro(self, height=7)
        self.log.pack(fill="x", padx=8, pady=(0, 8))

    # ---------- lista ----------
    def conferir(self) -> bool:
        self.colaboradores = ler_lista(self.txt.get("1.0", "end"))
        self.tabela.delete(*self.tabela.get_children())
        for i, c in enumerate(self.colaboradores):
            self.tabela.insert("", "end", iid=str(i), values=(c.nome, c.cpf_formatado, "; ".join(c.avisos)),
                               tags=("erro",) if c.avisos else ())
        validos = sum(1 for c in self.colaboradores if not c.avisos)
        self.lbl_total.config(text=f"{len(self.colaboradores)} na lista, {validos} pronto(s) para cadastrar")
        if not self.colaboradores:
            messagebox.showinfo("Conferir lista", "Digite ou cole ao menos um CPF e nome.")
            return False
        return True

    def abrir_fichas(self):
        """Lê CPF e nome das fichas (Registro de Empregado, EPI...) e põe na caixa de texto."""
        if self.enviando:
            return
        caminhos = filedialog.askopenfilenames(title="Escolha as fichas (Registro de Empregado ou EPI)",
                                               filetypes=[("PDF", "*.pdf")])
        if not caminhos:
            return
        from .ficha import ler_fichas

        lidos, problemas = [], []
        for caminho in caminhos:
            try:
                achados = ler_fichas(caminho)
            except Exception as erro:  # PDF corrompido, protegido etc.
                problemas.append(f"{Path(caminho).name}: {erro}")
                continue
            if not achados:
                problemas.append(f"{Path(caminho).name}: não achei CPF nem nome (o PDF pode ser uma imagem escaneada)")
            lidos += achados
        existentes = {c.cpf for c in ler_lista(self.txt.get("1.0", "end")) if c.cpf}
        novos = [c for c in lidos if not c.cpf or c.cpf not in existentes]
        if novos:
            atual = self.txt.get("1.0", "end").strip()
            linhas = [f"{c.cpf_formatado} {c.nome}".strip() for c in novos]
            self.txt.delete("1.0", "end")
            self.txt.insert("1.0", "\n".join(([atual] if atual else []) + linhas))
        for c in lidos:
            if c.avisos:
                self.log.escrever(f"{c.origem}: {', '.join(c.avisos)} (confira e corrija na caixa de texto)")
        for p in problemas:
            self.log.escrever(f"AVISO: {p}")
        self.log.escrever(f"Fichas lidas: {len(novos)} colaborador(es) adicionado(s)"
                          + (f", {len(lidos) - len(novos)} já estavam na lista." if len(lidos) > len(novos) else "."))
        if novos:
            self.conferir()
        elif problemas:
            messagebox.showwarning("Abrir fichas", "\n".join(problemas))

    def limpar(self):
        if self.enviando:
            return
        self.txt.delete("1.0", "end")
        self.tabela.delete(*self.tabela.get_children())
        self.colaboradores = []
        self.lbl_total.config(text="")

    def _situacao(self, i: int, texto: str, tag: str = ""):
        c = self.colaboradores[i]
        self.tabela.item(str(i), values=(c.nome, c.cpf_formatado, texto), tags=(tag,) if tag else ())
        self.tabela.see(str(i))

    # ---------- cadastro ----------
    def cadastrar(self):
        if self.enviando or not self.conferir():
            return
        validos = [i for i, c in enumerate(self.colaboradores) if not c.avisos]
        if not validos:
            messagebox.showerror("Cadastrar", "Nenhum colaborador está pronto: corrija os avisos da lista.")
            return
        if len(validos) < len(self.colaboradores) and not messagebox.askyesno(
                "Cadastrar", f"{len(self.colaboradores) - len(validos)} linha(s) com problema serão puladas "
                             f"(veja a coluna Situação).\n\nCadastrar os outros {len(validos)}?"):
            return
        login = DialogoLogin(self, "Entrar e cadastrar")
        if not login.resultado:
            return
        usuario, senha, lembrar = login.resultado
        if lembrar:
            credenciais.salvar(usuario, senha)
        self.enviando = True
        self.btn_cadastrar.config(state="disabled")
        threading.Thread(target=self._cadastrar_em_segundo_plano,
                         args=(validos, usuario, senha, self.modo_teste.get(), self.mostrar_navegador.get()),
                         daemon=True).start()

    def _cadastrar_em_segundo_plano(self, indices, usuario, senha, teste, visivel):
        from .plataforma import ErroPlataforma, Plataforma

        log = lambda texto: self.fila.put(("log", texto))  # noqa: E731
        contagem: dict[str, int] = {}
        try:
            with Plataforma(log=log, visivel=visivel) as p:
                p.login(usuario, senha)
                falhas_seguidas = 0
                for n, i in enumerate(indices, 1):
                    c = self.colaboradores[i]
                    log(f"({n}/{len(indices)}) {c.nome}")
                    self.fila.put(("situacao", i, "cadastrando...", ""))
                    try:
                        situacao, detalhe = p.cadastrar(c, confirmar=not teste)
                        falhas_seguidas = 0
                    except ErroPlataforma as erro:
                        situacao, detalhe = "erro", str(erro).splitlines()[0]
                        log(f"ERRO: {erro}")
                        falhas_seguidas += 1
                    except Exception as erro:  # falha inesperada do navegador
                        situacao, detalhe = "erro", detalhe_do_erro(erro)
                        log(f"ERRO: {detalhe}")
                        falhas_seguidas += 1
                    contagem[situacao] = contagem.get(situacao, 0) + 1
                    rotulo, tag = SITUACOES[situacao]
                    self.fila.put(("situacao", i, f"{rotulo}: {detalhe}" if detalhe else rotulo, tag))
                    if situacao in ("ja_cadastrado", "arquivado"):
                        log(f"AVISO: {c.nome} ({c.cpf_formatado}): {detalhe}")
                    if falhas_seguidas >= 3:
                        log("Três erros seguidos: parei para você conferir o registro e os prints em dados\\erros.")
                        break
                resumo = ", ".join(f"{SITUACOES[s][0]}: {q}" for s, q in contagem.items())
                self.fila.put(("fim", ("Modo teste concluído. " if teste else "Cadastro concluído. ") + resumo))
        except ErroPlataforma as erro:
            self.fila.put(("erro", str(erro)))
        except Exception as erro:
            self.fila.put(("erro", detalhe_do_erro(erro)))
        finally:
            self.fila.put(("liberar",))

    def _processar_fila(self):
        try:
            while True:
                tipo, *dado = self.fila.get_nowait()
                if tipo == "log":
                    self.log.escrever(dado[0])
                elif tipo == "situacao":
                    self._situacao(*dado)
                elif tipo == "erro":
                    self.log.escrever(f"ERRO: {dado[0]}")
                    messagebox.showerror("Erro no cadastro", dado[0])
                elif tipo == "fim":
                    self.log.escrever(dado[0])
                    messagebox.showinfo("Cadastro", dado[0])
                elif tipo == "liberar":
                    self.enviando = False
                    self.btn_cadastrar.config(state="normal")
        except queue.Empty:
            pass
        self.after(200, self._processar_fila)

    def esquecer_login(self):
        credenciais.apagar()
        self.log.escrever("Login salvo apagado deste computador.")


class DialogoLogin(tk.Toplevel):
    """Pede o login do responsável. Nada é gravado em arquivo."""

    def __init__(self, pai, texto_ok: str):
        super().__init__(pai)
        self.title("Login da plataforma Inbraep")
        self.resizable(False, False)
        self.transient(pai)
        self.resultado = None
        usuario, senha = credenciais.carregar()
        self.usuario = tk.StringVar(value=usuario)
        self.senha = tk.StringVar(value=senha)
        self.lembrar = tk.BooleanVar(value=True)

        quadro = ttk.Frame(self, padding=12)
        quadro.pack()
        ttk.Label(quadro, text="Usuário (CPF do responsável)").grid(row=0, column=0, sticky="w")
        entrada = ttk.Entry(quadro, textvariable=self.usuario, width=36)
        entrada.grid(row=1, column=0, pady=(0, 8))
        ttk.Label(quadro, text="Senha").grid(row=2, column=0, sticky="w")
        ttk.Entry(quadro, textvariable=self.senha, show="•", width=36).grid(row=3, column=0, pady=(0, 8))
        ttk.Checkbutton(quadro, text="Lembrar neste computador (Cofre do Windows)",
                        variable=self.lembrar).grid(row=4, column=0, sticky="w")
        botoes = ttk.Frame(quadro)
        botoes.grid(row=5, column=0, pady=(10, 0), sticky="e")
        ttk.Button(botoes, text="Cancelar", command=self.destroy).pack(side="right")
        ttk.Button(botoes, text=texto_ok, command=self._ok).pack(side="right", padx=6)
        self.bind("<Return>", lambda _: self._ok())
        entrada.focus_set()
        self.grab_set()
        pai.wait_window(self)

    def _ok(self):
        if self.usuario.get().strip() and self.senha.get():
            self.resultado = (self.usuario.get().strip(), self.senha.get(), self.lembrar.get())
            self.destroy()


class JanelaMonitoramento(tk.Toplevel):
    """Cola os nomes, lê o Acompanhamento e baixa os certificados de quem já concluiu."""

    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.title("Monitoramento de treinamentos")
        self.geometry("1000x620")
        self.minsize(780, 480)
        self.fila: queue.Queue = queue.Queue()
        self.rodando = False
        self.linhas: list[tuple[str, str, str, str]] = []

        quadro = ttk.Frame(self, padding=8)
        quadro.pack(fill="both", expand=True)
        ttk.Label(quadro, text="Nomes dos colaboradores (um por linha; pode colar vários de uma vez):").pack(anchor="w")
        self.txt_nomes = tk.Text(quadro, height=7, wrap="none")
        self.txt_nomes.pack(fill="x", pady=(2, 6))

        botoes = ttk.Frame(quadro)
        botoes.pack(fill="x")
        self.btn_buscar = ttk.Button(botoes, text="Buscar progresso", command=self.buscar)
        self.btn_buscar.pack(side="left")
        self.baixar = tk.BooleanVar(value=True)
        ttk.Checkbutton(botoes, text="Baixar certificado de quem concluiu", variable=self.baixar).pack(side="left", padx=8)
        ttk.Button(botoes, text="Abrir pasta dos certificados",
                   command=lambda: abrir_pasta(pasta_certificados())).pack(side="right")
        ttk.Button(botoes, text="Copiar resultado", command=self.copiar).pack(side="right", padx=6)

        colunas = ("aluno", "curso", "conclusao", "situacao")
        self.tabela = ttk.Treeview(quadro, columns=colunas, show="headings")
        for col, titulo, largura in [("aluno", "Aluno", 240), ("curso", "Curso", 330),
                                     ("conclusao", "Conclusão", 80), ("situacao", "Situação / certificado", 280)]:
            self.tabela.heading(col, text=titulo)
            self.tabela.column(col, width=largura, anchor="w")
        self.tabela.tag_configure("ok", foreground="#15803d")
        self.tabela.tag_configure("falta", foreground="#b45309")
        self.tabela.pack(fill="both", expand=True, pady=6)

        self.log = Registro(quadro, height=6)
        self.log.pack(fill="x")
        self.txt_nomes.focus_set()
        self.after(200, self._processar_fila)

    def buscar(self):
        if self.rodando:
            return
        nomes = nomes_colados(self.txt_nomes.get("1.0", "end"))
        if not nomes:
            messagebox.showinfo("Monitoramento", "Cole ou digite ao menos um nome.", parent=self)
            return
        login = DialogoLogin(self, "Entrar e buscar")
        if not login.resultado:
            return
        usuario, senha, lembrar = login.resultado
        if lembrar:
            credenciais.salvar(usuario, senha)
        self.rodando = True
        self.btn_buscar.config(state="disabled")
        self.tabela.delete(*self.tabela.get_children())
        self.linhas.clear()
        threading.Thread(target=self._buscar_em_segundo_plano,
                         args=(nomes, usuario, senha, self.baixar.get(), self.app.mostrar_navegador.get()),
                         daemon=True).start()

    def _buscar_em_segundo_plano(self, nomes, usuario, senha, baixar, visivel):
        from .plataforma import ErroPlataforma, Plataforma

        log = lambda texto: self.fila.put(("log", texto))  # noqa: E731
        achados = 0
        try:
            with Plataforma(log=log, visivel=visivel) as p:
                p.login(usuario, senha)
                pasta = pasta_certificados() if baixar else None
                for n, nome in enumerate(nomes, 1):
                    log(f"({n}/{len(nomes)}) {nome}")
                    try:
                        achou = self._buscar_um(p, nome, pasta, log)
                    except ErroPlataforma as erro:
                        log(f"ERRO: {nome}: {erro}")
                        self.fila.put(("linha", (nome, "erro na busca (veja o registro)", "-", ""), "falta"))
                        continue
                    except Exception as erro:  # um nome com problema não para os outros
                        log(f"ERRO: {nome}: {detalhe_do_erro(erro)}")
                        self.fila.put(("linha", (nome, "erro na busca (veja o registro)", "-", ""), "falta"))
                        continue
                    achados += achou
                self.fila.put(("fim", f"Pronto: {achados} de {len(nomes)} colaborador(es) encontrados."))
        except ErroPlataforma as erro:
            self.fila.put(("erro", str(erro)))
        except Exception as erro:
            self.fila.put(("erro", detalhe_do_erro(erro)))
        finally:
            self.fila.put(("liberar",))

    def _buscar_um(self, p, nome: str, pasta: Path | None, log) -> bool:
        """Acompanhamento; se não estiver lá (ou já concluiu), Histórico e Certificados."""
        em_andamento = p.acompanhamento(nome)
        abertos = [m for m in em_andamento if not m.concluida]
        concluidos_acomp = [m for m in em_andamento if m.concluida]
        for m in abertos:
            self.fila.put(("linha", (m.aluno, m.curso, m.conclusao, m.status or "em andamento"), ""))
        if em_andamento and not concluidos_acomp:
            return True
        if not em_andamento:
            log(f"{nome} não está no Acompanhamento; procurando em Histórico e Certificados...")
        concluidos = p.historico(nome)
        for m in concluidos:
            if pasta is None:
                situacao, tag = "concluído", "ok"
            else:
                situacao, tag = self._certificado(p, m, pasta, log)
            self.fila.put(("linha", (m.aluno, m.curso, "100%", situacao), tag))
        no_historico = {normalizar(m.curso) for m in concluidos}
        for m in concluidos_acomp:
            if normalizar(m.curso) not in no_historico:
                self.fila.put(("linha", (m.aluno, m.curso, m.conclusao,
                                         "concluído; certificado ainda não está no Histórico"), "ok"))
        if not em_andamento and not concluidos:
            self.fila.put(("linha", (nome, "não encontrado (sem cadastro ou sem curso)", "-", ""), "falta"))
            return False
        return True

    @staticmethod
    def _certificado(p, m, pasta: Path, log) -> tuple[str, str]:
        if (pasta / nome_certificado(m.aluno, m.curso)).exists():
            return "concluído; certificado já baixado", "ok"
        log(f"Baixando o certificado de {m.aluno} ({m.curso})...")
        try:
            destino = p.baixar_certificado(m, pasta)
        except Exception as erro:  # um certificado com problema não para os outros
            texto = str(erro).splitlines()[0] if str(erro) else detalhe_do_erro(erro)
            log(f"ERRO no certificado de {m.aluno}: {texto}")
            return "concluído; erro ao baixar o certificado (veja o registro)", "falta"
        log(f"Certificado salvo: {destino}")
        return f"concluído; salvo: {destino.name}", "ok"

    def copiar(self):
        texto = "\n".join("\t".join(l) for l in [("Aluno", "Curso", "Conclusão", "Situação")] + self.linhas)
        self.clipboard_clear()
        self.clipboard_append(texto)
        self.log.escrever("Resultado copiado (cole no Excel ou no e-mail).")

    def _processar_fila(self):
        if not self.winfo_exists():
            return
        try:
            while True:
                tipo, *dado = self.fila.get_nowait()
                if tipo == "log":
                    self.log.escrever(dado[0])
                elif tipo == "linha":
                    valores, tag = dado
                    self.linhas.append(valores)
                    self.tabela.insert("", "end", values=valores, tags=(tag,) if tag else ())
                elif tipo == "erro":
                    self.log.escrever(f"ERRO: {dado[0]}")
                    messagebox.showerror("Erro no monitoramento", dado[0], parent=self)
                elif tipo == "fim":
                    self.log.escrever(dado[0])
                elif tipo == "liberar":
                    self.rodando = False
                    self.btn_buscar.config(state="normal")
        except queue.Empty:
            pass
        self.after(200, self._processar_fila)


def main():
    App().mainloop()
