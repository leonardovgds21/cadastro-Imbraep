"""Automação da plataforma AVAPRO (Inbraep) em segundo plano.

Usa o Microsoft Edge que já vem no Windows (ou o Chrome, se o Edge falhar),
controlado pelo Selenium. O fluxo é o mesmo que a pessoa faz na mão:

1. Login (CPF/login e senha) e escolha do perfil "Responsável".
2. Cadastro: Colaboradores > Cadastrar (/employee/create). Digita o CPF e sai
   do campo: a plataforma confere o CPF e
   - avisa "Já existe um funcionário registrado" (pula);
   - pergunta "Restaurar funcionário?" se ele foi arquivado (pula e avisa);
   - avisa que o CPF "já está cadastrado no Sistema AVAPRO" e preenche o nome
     sozinha (só vincula à empresa);
   - ou libera o campo Nome Completo. Depois clica em Salvar.
3. Monitoramento: Acompanhamento (/course-in-progress), filtra pelo aluno e
   abre cada linha para ler a Conclusão (%). Quem não está lá é procurado em
   Histórico e Certificados (/company-historial): Certificado > "Com
   assinatura" (ou "Sem assinatura") > Download.
"""

from __future__ import annotations

import base64
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .config import URL_BASE, pasta_dados, pasta_downloads
from .entrada import Colaborador, so_numeros
from .nomes import mesmo_nome, nome_certificado, normalizar, palavras

Log = Callable[[str], None]

# Acha o elemento visível cujo texto (ou value) contém o procurado, ignorando
# maiúsculas, acentos, espaços e ícones; fica o mais interno com o texto e
# sobe até o que é clicável. arguments[1] limita a busca a um elemento.
_JS_ACHAR_BOTAO = """
const alvo = arguments[0], raiz = arguments[1] || document;
const norm = t => (t || '').normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').replace(/\\s+/g, ' ').trim().toLowerCase();
const visivel = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
const tem = e => norm(e.textContent).includes(alvo) || norm(e.value).includes(alvo);
const achados = [...raiz.querySelectorAll('a, button, input[type=button], input[type=submit], [role=button], span, h4, li')]
    .filter(tem).filter(visivel);
const internos = achados.filter(e => !achados.some(o => o !== e && e.contains(o)));
const el = internos[0];
if (!el) return null;
return el.closest('a, button, [role=button], [onclick]') || el;
"""

# O alerta do SweetAlert2 aberto: {titulo, texto} ou null.
_JS_SWAL = """
const p = document.querySelector('.swal2-container .swal2-popup');
if (!p || !(p.offsetWidth || p.offsetHeight) || p.classList.contains('swal2-hide')) return null;
const t = s => { const e = p.querySelector(s); return e ? e.innerText.replace(/\\s+/g, ' ').trim() : ''; };
return {titulo: t('.swal2-title'), texto: t('.swal2-html-container') || t('.swal2-content')};
"""

# Mensagens de erro de validação visíveis (campos com problema).
_JS_ERROS = """
const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
return [...document.querySelectorAll('.is-danger, .text-danger, .help-block, .invalid-feedback, .error-col small')]
    .filter(e => vis(e) && !['INPUT', 'SELECT', 'TEXTAREA'].includes(e.tagName))
    .map(e => e.innerText.replace(/\\s+/g, ' ').trim()).filter(t => t);
"""

# O aviso vermelho do canto da tela (ex.: login recusado), ou "".
_JS_ALERTA = """
const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
const a = [...document.querySelectorAll('.alert-danger, .alert-warning')].find(vis);
return a ? a.innerText.replace(/\\bFechar\\b/g, ' ').replace(/\\s+/g, ' ').trim() : '';
"""

# A janela (modal do Bootstrap) visível na frente, ou null.
_JS_MODAL = """
const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
const modais = [...document.querySelectorAll('.modal')].filter(m => vis(m) && m.querySelector('.modal-content, .modal-body'));
return modais.length ? modais[modais.length - 1] : null;
"""

# Linhas do Acompanhamento: [usuario, curso, status, nº da linha]. A tabela é
# achada pelo cabeçalho (Usuário e Curso); as linhas de detalhe (uma célula só)
# ficam de fora. null enquanto a tabela não existe.
_JS_LINHAS_ACOMPANHAMENTO = """
const norm = t => (t || '').normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').replace(/\\s+/g, ' ').trim().toLowerCase();
const tabela = [...document.querySelectorAll('table')].find(t => {
    const cab = [...t.querySelectorAll('thead th')].map(th => norm(th.textContent));
    return cab.includes('usuario') && cab.includes('curso');
});
if (!tabela) return null;
const linhaCab = [...tabela.querySelectorAll('thead tr')].find(tr =>
    [...tr.children].some(th => norm(th.textContent) === 'usuario')) || tabela.querySelector('thead');
const cab = [...linhaCab.children].map(th => norm(th.textContent));
const [u, c, s] = [cab.indexOf('usuario'), cab.indexOf('curso'), cab.indexOf('status')];
const linhas = [...tabela.querySelectorAll('tbody > tr')].filter(tr => tr.children.length > 3);
return linhas.map((tr, n) => {
    const td = [...tr.children];
    const txt = i => i >= 0 && td[i] ? td[i].innerText.trim() : '';
    return [txt(u).split('\\n')[0].trim(), txt(c).replace(/\\s+/g, ' '), txt(s).replace(/\\s+/g, ' '), n];
}).filter(l => l[0]);
"""

# Abre o detalhe da linha arguments[0] do Acompanhamento (botão da 1ª coluna).
_JS_LINHA_ACOMPANHAMENTO = """
const norm = t => (t || '').normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').replace(/\\s+/g, ' ').trim().toLowerCase();
const tabela = [...document.querySelectorAll('table')].find(t => {
    const cab = [...t.querySelectorAll('thead th')].map(th => norm(th.textContent));
    return cab.includes('usuario') && cab.includes('curso');
});
if (!tabela) return null;
return [...tabela.querySelectorAll('tbody > tr')].filter(tr => tr.children.length > 3)[arguments[0]] || null;
"""

# A Conclusão do detalhe aberto logo abaixo da linha arguments[0], ou null.
_JS_CONCLUSAO = """
const norm = t => (t || '').normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').replace(/\\s+/g, ' ').trim().toLowerCase();
const linha = arguments[0];
const det = linha && linha.nextElementSibling;
if (!det || det.children.length > 3) return null;
for (const th of det.querySelectorAll('th, b, strong')) {
    if (norm(th.textContent).replace(/[:\\-\\s]+$/, '') === 'conclusao') {
        const td = th.tagName === 'TH' ? th.nextElementSibling : null;
        const texto = td ? td.innerText : (th.parentElement.innerText.split(/conclus[aã]o/i)[1] || '');
        return texto.replace(/^[\\s:\\-]+/, '').trim() || '-';
    }
}
return null;
"""

# Linhas do Histórico e Certificados que têm o botão "Certificado":
# [aluno, curso, nº da linha]. As colunas vêm do cabeçalho, se houver
# (Aluno/Nome e Curso); senão, a 2ª e a 4ª coluna, como na tela.
_JS_LINHAS_HISTORICO = """
const norm = t => (t || '').normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').replace(/\\s+/g, ' ').trim().toLowerCase();
const comBotao = tr => [...tr.querySelectorAll('button, a')].some(b => norm(b.textContent) === 'certificado');
const linhas = [...document.querySelectorAll('table tbody > tr')].filter(comBotao);
if (!linhas.length) return [];
const tabela = linhas[0].closest('table');
const cab = [...tabela.querySelectorAll('thead th')].map(th => norm(th.textContent));
let a = cab.findIndex(c => c === 'aluno' || c === 'nome' || c === 'usuario' || c.startsWith('nome do aluno'));
let c = cab.findIndex(c => c === 'curso' || c.startsWith('curso') || c === 'treinamento');
if (a < 0 || c < 0) { a = 1; c = 3; }
return linhas.map((tr, n) => {
    const td = [...tr.children];
    const txt = i => td[i] ? td[i].innerText.replace(/\\s+/g, ' ').trim() : '';
    return [txt(a), txt(c), n];
}).filter(l => l[0]);
"""

_JS_LINHA_HISTORICO = """
const norm = t => (t || '').normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').replace(/\\s+/g, ' ').trim().toLowerCase();
const comBotao = tr => [...tr.querySelectorAll('button, a')].some(b => norm(b.textContent) === 'certificado');
return [...document.querySelectorAll('table tbody > tr')].filter(comBotao)[arguments[0]] || null;
"""

_JS_CARREGANDO = """
const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
return [...document.querySelectorAll('.spinner-avapro, .vld-overlay, .loading-overlay, .swal2-loading')].some(vis);
"""


SITES_EXTRAS = [
    "*player.vimeo.com*", "*three.min.js*", "*pandavideo*", "*googletagmanager*",
    "*google-analytics*", "*facebook.net*", "*connect.facebook*", "*video-js*", "*video.js*",
]


class ErroPlataforma(Exception):
    pass


@dataclass
class Matricula:
    aluno: str
    curso: str
    conclusao: str  # como está na tela ("45%", "-")
    status: str = ""
    origem: str = "acompanhamento"  # ou "historico"
    linha: int = -1

    @property
    def progresso(self) -> float | None:
        from .nomes import ler_progresso

        return ler_progresso(self.conclusao)

    @property
    def concluida(self) -> bool:
        p = self.progresso
        return self.origem == "historico" or (p is not None and p >= 99.995) or "conclu" in normalizar(self.status)


def termos_de_busca(nome: str) -> list[str]:
    """O nome inteiro e, se não achar, o primeiro + último nome e o sobrenome
    mais longo (a busca da plataforma procura o texto inteiro)."""
    p = palavras(nome)
    termos = [" ".join(nome.split())]
    if len(p) > 2:
        termos.append(f"{p[0]} {p[-1]}")
    if len(p) > 1:
        termos.append(max(p[1:], key=len))
    return list(dict.fromkeys(t for t in termos if t))


class Plataforma:
    def __init__(self, log: Log = print, visivel: bool = False, espera: int = 30):
        self.log = log
        self.visivel = visivel
        self.espera = espera
        self.driver: webdriver.Remote | None = None
        self.pasta_downloads = pasta_downloads()

    # ---------- navegador ----------
    def __enter__(self):
        self.driver = self._abrir_navegador()
        self.driver.set_page_load_timeout(120)
        self._bloquear_extras()
        return self

    def __exit__(self, *_):
        if self.driver:
            self.driver.quit()

    def _abrir_navegador(self):
        erros = []
        for nome, classe, opcoes in [
            ("Edge", webdriver.Edge, webdriver.EdgeOptions()),
            ("Chrome", webdriver.Chrome, webdriver.ChromeOptions()),
        ]:
            if not self.visivel:
                opcoes.add_argument("--headless=new")
            opcoes.add_argument("--window-size=1400,1000")
            opcoes.add_argument("--lang=pt-BR")
            opcoes.add_experimental_option("prefs", {
                "download.default_directory": str(self.pasta_downloads),
                "download.prompt_for_download": False,
                "plugins.always_open_pdf_externally": True,
            })
            try:
                driver = classe(options=opcoes)
                self.log(f"Navegador {nome} aberto{' (invisível)' if not self.visivel else ''}.")
                return driver
            except WebDriverException as erro:
                erros.append(f"{nome}: {erro.msg}")
        raise ErroPlataforma("Não consegui abrir o Edge nem o Chrome.\n" + "\n".join(erros))

    def _bloquear_extras(self):
        """A página de login carrega players de vídeo, 3D e estatísticas de outros
        sites, que não são usados aqui; numa rede lenta ou com bloqueios eles
        atrasam o carregamento. O navegador automatizado não os baixa."""
        try:
            self.driver.execute_cdp_cmd("Network.enable", {})
            self.driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": SITES_EXTRAS})
        except WebDriverException:
            pass

    def _esperar(self, condicao, tempo: int | None = None, o_que: str | None = None):
        """Espera a condição. Com `o_que`, um tempo esgotado vira um erro claro
        dizendo o que faltou, com print e resumo da página salvos em dados/erros."""
        try:
            return WebDriverWait(
                self.driver, tempo or self.espera, ignored_exceptions=[StaleElementReferenceException]
            ).until(condicao)
        except TimeoutException:
            if not o_que:
                raise
            pasta = self.salvar_diagnostico(o_que)
            raise ErroPlataforma(
                f"Não encontrei {o_que} na página {self.driver.current_url}\n\n"
                f"Print e resumo da página salvos em:\n{pasta}"
            ) from None

    def _erro(self, mensagem: str, etapa: str) -> ErroPlataforma:
        pasta = self.salvar_diagnostico(etapa)
        return ErroPlataforma(f"{mensagem}\n\nPrint e resumo da página salvos em:\n{pasta}")

    def salvar_diagnostico(self, etapa: str) -> Path | None:
        """Salva um print da tela e a lista de campos, botões e avisos da página."""
        d = self.driver
        try:
            pasta = pasta_dados() / "erros"
            pasta.mkdir(parents=True, exist_ok=True)
            base = pasta / datetime.now().strftime("%Y-%m-%d_%H%M%S")
            d.save_screenshot(str(base.with_suffix(".png")))
            linhas = [f"Etapa: {etapa}", f"URL: {d.current_url}", f"Título: {d.title}", "", "Campos:"]
            for e in d.find_elements(By.CSS_SELECTOR, "input, select, textarea"):
                linhas.append(
                    f"  <{e.tag_name} type={e.get_attribute('type')} name={e.get_attribute('name')} "
                    f"id={e.get_attribute('id')} placeholder={e.get_attribute('placeholder')} "
                    f"visível={e.is_displayed()} ativo={e.is_enabled()}>")
            linhas += ["", "Botões e links:"]
            for e in d.find_elements(By.CSS_SELECTOR, "button, a, input[type='submit']"):
                texto = (e.text or e.get_attribute("value") or "").strip().replace("\n", " ")
                if texto:
                    linhas.append(f"  <{e.tag_name}> {texto[:60]}  href={e.get_attribute('href')}")
            linhas += ["", "Cabeçalhos de tabela:"]
            for t in d.find_elements(By.CSS_SELECTOR, "table"):
                cab = " | ".join(th.text.strip() for th in t.find_elements(By.CSS_SELECTOR, "th") if th.text.strip())
                if cab:
                    linhas.append(f"  {cab[:300]}")
            swal = d.execute_script(_JS_SWAL)
            if swal:
                linhas += ["", f"Alerta aberto: {swal['titulo']} - {swal['texto']}"]
            erros = d.execute_script(_JS_ERROS) or []
            if erros:
                linhas += ["", "Mensagens de erro: " + " | ".join(erros)]
            linhas += ["", f"Estado da página: {d.execute_script('return document.readyState')}",
                       "Recursos lentos ou que falharam:"]
            for nome, duracao, tamanho in d.execute_script(
                    "return performance.getEntriesByType('resource').filter(r => r.duration > 3000 || !r.transferSize)"
                    ".map(r => [r.name, Math.round(r.duration), r.transferSize]).slice(0, 40);") or []:
                linhas.append(f"  {duracao} ms, {tamanho} bytes: {nome[:150]}")
            texto = (d.execute_script("return document.body ? document.body.innerText : ''") or "").strip()
            linhas += ["", "Texto da página (início):", texto[:1500] or "(vazia)"]
            base.with_suffix(".txt").write_text("\n".join(linhas), encoding="utf-8")
            return base.with_suffix(".png")
        except Exception:  # o diagnóstico nunca pode esconder o erro original
            return None

    def _clicar(self, elemento):
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elemento)
        try:
            elemento.click()
        except WebDriverException:  # coberto por outro elemento: clica via JS
            self.driver.execute_script("arguments[0].click();", elemento)

    def _botao(self, texto: str, raiz=None):
        return self.driver.execute_script(_JS_ACHAR_BOTAO, normalizar(texto), raiz)

    def _esperar_carregar(self, tempo: int = 30):
        """Espera a página e o "carregando" da plataforma sumirem."""
        try:
            self._esperar(lambda drv: drv.execute_script("return document.readyState") == "complete"
                          and not drv.execute_script(_JS_CARREGANDO), tempo)
        except TimeoutException:
            pass

    def _swal(self) -> dict | None:
        try:
            return self.driver.execute_script(_JS_SWAL)
        except WebDriverException:
            return None

    def _responder_swal(self, confirmar: bool):
        seletor = ".swal2-confirm" if confirmar else ".swal2-cancel, .swal2-close, .swal2-deny"
        for botao in self.driver.find_elements(By.CSS_SELECTOR, seletor):
            if botao.is_displayed():
                self._clicar(botao)
                break
        else:
            self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        try:
            self._esperar(lambda drv: not drv.execute_script(_JS_SWAL), 10)
        except TimeoutException:
            pass

    # ---------- login ----------
    def login(self, usuario: str, senha: str) -> None:
        d = self.driver
        self.log("Entrando na plataforma...")
        senha_visivel = EC.visibility_of_element_located((By.CSS_SELECTOR, "input#password, input[type='password']"))
        campo_senha = None
        for tentativa in range(2):  # a página às vezes demora a montar o formulário: recarrega uma vez
            try:
                d.get(f"{URL_BASE}/login?redirectTo=%2Fdashboard-company")
            except TimeoutException:
                self.log("A página de login demorou para terminar de carregar; conferindo se o formulário apareceu...")
            try:
                campo_senha = self._esperar(senha_visivel, 60)
                break
            except TimeoutException:
                if tentativa == 0:
                    self.log("O formulário de login não apareceu; recarregando a página...")
        if campo_senha is None:
            raise self._erro("Não encontrei o campo de senha do login (a página não carregou o formulário).",
                             "o campo de senha do login")
        campo_usuario = self._campo_usuario_login()
        if not campo_usuario:
            raise self._erro("Não encontrei o campo de usuário (CPF) do login.", "login")
        valor = usuario.strip()
        if len(so_numeros(valor)) == 11 and not any(ch.isalpha() or ch == "@" for ch in valor):
            valor = so_numeros(valor)  # o campo de CPF tem máscara
        campo_usuario.click()
        campo_usuario.send_keys(Keys.CONTROL, "a")
        campo_usuario.send_keys(Keys.DELETE)
        campo_usuario.send_keys(valor)
        campo_senha.click()
        campo_senha.send_keys(Keys.CONTROL, "a")
        campo_senha.send_keys(Keys.DELETE)
        campo_senha.send_keys(senha)
        botoes = [b for b in d.find_elements(By.CSS_SELECTOR, "#submit-form-login") if b.is_displayed()]
        if botoes and botoes[0].is_enabled():
            self._clicar(botoes[0])
        else:
            campo_senha.send_keys(Keys.ENTER)

        def saiu_do_login(drv):
            url = drv.current_url
            if "/login/mfa" in url:
                return "mfa"
            if "/login" not in url:
                return "ok"
            swal = drv.execute_script(_JS_SWAL)
            if swal:
                return ("swal", swal)
            alerta = drv.execute_script(_JS_ALERTA)  # "Atenção! Os dados fornecidos são inválidos."
            if alerta:
                return ("swal", {"titulo": "", "texto": alerta})
            return False

        try:
            resultado = self._esperar(saiu_do_login, 40)
        except TimeoutException:
            erros = d.execute_script(_JS_ERROS) or []
            raise self._erro(f"Login recusado. {' '.join(erros)}".strip(), "login") from None
        if resultado == "mfa":
            raise self._erro("A plataforma pediu um código de verificação (MFA). Entre uma vez pelo navegador "
                             "neste computador e tente de novo.", "login com verificação")
        if isinstance(resultado, tuple):
            swal = resultado[1]
            raise self._erro(f"Login recusado: {swal['titulo']} {swal['texto']}".strip(), "login")
        self.log("Login feito.")
        self.escolher_perfil()

    def _campo_usuario_login(self):
        d = self.driver
        for seletor in ("input#cpf", "input[name='cpf']", "input#passport", "input[name='username']",
                        "input[type='email']", "input[type='text']"):
            for campo in d.find_elements(By.CSS_SELECTOR, seletor):
                if campo.is_displayed() and campo.get_attribute("id") != "password":
                    return campo
        return None

    def escolher_perfil(self, perfil: str = "Responsável") -> None:
        """Clica no quadro do perfil "Responsável" (se a plataforma perguntar)."""
        d = self.driver
        alvo = normalizar(perfil)
        js = """
            const alvo = arguments[0];
            const norm = t => (t || '').normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').replace(/\\s+/g, ' ').trim().toLowerCase();
            const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
            const titulos = [...document.querySelectorAll('.title-box-reference, .small-box h4, .small-box h3')]
                .filter(e => vis(e) && norm(e.textContent) === alvo);
            if (titulos.length) {
                const caixa = titulos[0].closest('a') || titulos[0].closest('.small-box');
                const rodape = caixa.querySelector('.small-box-footer');
                return [caixa.closest('a') || rodape || caixa, norm((rodape || caixa).textContent).includes('perfil atual')];
            }
            for (const s of document.querySelectorAll('select')) {
                const o = [...s.options].find(o => norm(o.textContent).includes(alvo));
                if (o && vis(s)) return [s, false, o.value];
            }
            return null;"""
        fim = time.time() + 20
        achado = None
        while time.time() < fim:
            try:
                achado = d.execute_script(js, alvo)
            except WebDriverException:
                achado = None
            if achado:
                break
            if self._menu_carregado() and time.time() > fim - 12:
                break  # já está no painel, sem perguntar o perfil
            time.sleep(1)
        if not achado:
            self.log("A plataforma não pediu o perfil; seguindo com o perfil atual.")
            return
        elemento, atual = achado[0], achado[1]
        if atual:
            self.log(f"Perfil \"{perfil}\" já é o atual.")
            return
        if elemento.tag_name.lower() == "select":
            from selenium.webdriver.support.ui import Select

            Select(elemento).select_by_value(achado[2])
        else:
            self._clicar(elemento)
        self.log(f"Perfil \"{perfil}\" escolhido.")
        time.sleep(2)
        self._esperar_carregar()

    def _menu_carregado(self) -> bool:
        try:
            return bool(self.driver.execute_script(
                "return [...document.querySelectorAll('.sidebar-menu a, .main-sidebar a, nav a')]"
                ".some(a => /colaboradores|painel principal|acompanhamento/i.test(a.textContent));"))
        except WebDriverException:
            return False

    def _abrir(self, rota: str, pronto, o_que: str, menu: list[str] | None = None):
        """Abre a tela pelo endereço; se não carregar, tenta pelo menu."""
        d = self.driver
        d.get(f"{URL_BASE}{rota}")
        if "/login" in d.current_url and d.find_elements(By.CSS_SELECTOR, "input[type='password']"):
            raise self._erro("A plataforma voltou para a tela de login. Confira o usuário e a senha "
                             "(use \"Esquecer login salvo\" e digite de novo).", f"abrir {rota}")
        try:
            return self._esperar(pronto, 25)
        except TimeoutException:
            if not menu:
                raise self._erro(f"Não encontrei {o_que} na página {d.current_url}", o_que) from None
        self.log(f"Abrindo {' > '.join(menu)} pelo menu...")
        d.get(f"{URL_BASE}/dashboard-company")
        self._esperar_carregar()
        for item in menu:
            botao = self._esperar(lambda drv: self._botao(item), 20, o_que=f"o item \"{item}\" do menu")
            self._clicar(botao)
            time.sleep(1)
        return self._esperar(pronto, 30, o_que=o_que)

    # ---------- cadastro ----------
    def cadastrar(self, c: Colaborador, confirmar: bool = True) -> tuple[str, str]:
        """Cadastra um colaborador. Devolve (situação, detalhe); situação é
        cadastrado, vinculado, ja_cadastrado, arquivado, teste ou erro."""
        d = self.driver

        def campo_cpf(drv):
            campos = [e for e in drv.find_elements(By.CSS_SELECTOR, "input[name='document']") if e.is_displayed()]
            return campos[0] if campos and campos[0].is_enabled() else False

        cpf = self._abrir("/employee/create", campo_cpf, "o campo CPF do cadastro", ["Colaboradores", "Cadastrar"])
        self._esperar_carregar()
        self._clicar(cpf)
        cpf.send_keys(Keys.CONTROL, "a")
        cpf.send_keys(Keys.DELETE)
        cpf.send_keys(c.cpf)
        cpf.send_keys(Keys.TAB)  # sair do campo dispara a conferência do CPF

        def conferiu(drv):
            swal = drv.execute_script(_JS_SWAL)
            if swal:
                return ("alerta", swal)
            if drv.execute_script(_JS_CARREGANDO):
                return False
            nomes = [e for e in drv.find_elements(By.CSS_SELECTOR, "input[name='name']") if e.is_displayed()]
            if nomes and nomes[0].is_enabled():
                return ("livre", None)
            erros = drv.execute_script(_JS_ERROS) or []
            if any("cpf" in normalizar(e) or "document" in normalizar(e) for e in erros):
                return ("erro", " ".join(erros))
            return False

        try:
            tipo, dado = self._esperar(conferiu, 30)
        except TimeoutException:
            raise self._erro("A plataforma não respondeu à conferência do CPF.", f"conferir CPF de {c.nome}") from None

        vinculado = False
        if tipo == "erro":
            return "erro", f"CPF recusado pela plataforma: {dado}"
        if tipo == "alerta":
            titulo, texto = normalizar(dado["titulo"]), normalizar(dado["texto"])
            if "restaurar" in titulo or "arquivado" in texto:
                self._responder_swal(confirmar=False)
                return "arquivado", "já existe, mas está arquivado na empresa (restaure à mão em Colaboradores, se quiser)"
            if "ja existe um funcionario" in texto or "ja existe" in texto and "funcionario" in texto:
                self._responder_swal(confirmar=False)
                return "ja_cadastrado", "CPF já cadastrado como colaborador (pulado)"
            if "ja esta cadastrado" in texto:
                self._responder_swal(confirmar=True)  # "Entendi": o nome vem da conta que já existe
                vinculado = True
            else:
                detalhe = f"{dado['titulo']} {dado['texto']}".strip()
                self._responder_swal(confirmar=False)
                raise self._erro(f"Aviso inesperado ao conferir o CPF: {detalhe}", f"conferir CPF de {c.nome}")

        nome_tela = ""
        campo_nome = d.find_element(By.CSS_SELECTOR, "input[name='name']")
        if vinculado:
            nome_tela = (campo_nome.get_attribute("value") or "").strip()
        else:
            self._clicar(campo_nome)
            campo_nome.send_keys(Keys.CONTROL, "a")
            campo_nome.send_keys(Keys.DELETE)
            campo_nome.send_keys(c.nome)

        def salvar_ativo(drv):
            for b in drv.find_elements(By.XPATH, "//button[normalize-space(.)='Salvar']"):
                if b.is_displayed() and b.is_enabled():
                    return b
            return False

        try:
            salvar = self._esperar(salvar_ativo, 10)
        except TimeoutException:
            erros = d.execute_script(_JS_ERROS) or []
            self.salvar_diagnostico(f"botão Salvar de {c.nome}")
            return "erro", "a plataforma não liberou o Salvar" + (f": {' '.join(erros)}" if erros else "")

        detalhe_vinculo = f"já tinha conta na AVAPRO como \"{nome_tela}\"" if vinculado else ""
        if not confirmar:
            return "teste", "pronto para salvar (modo teste, nada foi salvo)" + (
                f"; {detalhe_vinculo}" if detalhe_vinculo else "")

        url_antes = d.current_url
        self._clicar(salvar)

        def salvou(drv):
            swal = drv.execute_script(_JS_SWAL)
            if swal:
                return ("alerta", swal)
            texto = normalizar(drv.execute_script("return document.body.innerText") or "")
            if "cadastrado com sucesso" in texto:
                return ("ok", None)
            if drv.current_url != url_antes and "/employee/create" not in drv.current_url:
                return ("ok", None)
            if drv.execute_script(_JS_CARREGANDO):
                return False
            erros = drv.execute_script(_JS_ERROS) or []
            if erros:
                return ("erro", " ".join(erros))
            return False

        try:
            tipo, dado = self._esperar(salvou, 40)
        except TimeoutException:
            raise self._erro("Cliquei em Salvar, mas a plataforma não confirmou o cadastro.",
                             f"salvar {c.nome}") from None
        if tipo == "erro":
            time.sleep(2)  # erro de validação some se o salvamento só estava demorando
            if "cadastrado com sucesso" not in normalizar(d.execute_script("return document.body.innerText") or ""):
                self.salvar_diagnostico(f"salvar {c.nome}")
                return "erro", f"a plataforma recusou: {dado}"
        if tipo == "alerta":
            titulo, texto = normalizar(dado["titulo"]), normalizar(dado["texto"])
            if "sucesso" not in titulo and "sucesso" not in texto:
                self._responder_swal(confirmar=True)
                self.salvar_diagnostico(f"salvar {c.nome}")
                return "erro", f"{dado['titulo']} {dado['texto']}".strip()
            self._responder_swal(confirmar=True)
        if vinculado:
            return "vinculado", f"vinculado à empresa ({detalhe_vinculo})"
        return "cadastrado", "cadastrado com sucesso"

    # ---------- filtros ----------
    def _filtrar(self, termo: str, botao_modal: bool):
        """Abre "Filtrar", digita o aluno e filtra. Espera a tabela recarregar."""
        d = self.driver
        self._esperar_carregar()
        d.execute_script("document.querySelectorAll('table tbody > tr').forEach(tr => tr.dataset.imbraepVelho = '1');")
        campo = next((e for e in d.find_elements(By.CSS_SELECTOR, "input#user_name") if e.is_displayed()), None)
        if not campo:
            abrir = self._esperar(lambda drv: self._botao("alterar filtro") or self._botao("filtrar"), 20,
                                  o_que="o botão \"Filtrar\"")
            self._clicar(abrir)
            campo = self._esperar(EC.visibility_of_element_located((By.CSS_SELECTOR, "input#user_name")), 15,
                                  o_que="o campo de aluno do filtro")
        self._clicar(campo)
        campo.send_keys(Keys.CONTROL, "a")
        campo.send_keys(Keys.DELETE)
        campo.send_keys(termo)
        if botao_modal:
            modal = d.execute_script(_JS_MODAL)
            filtrar = self._botao("filtrar", modal) if modal else None
            if filtrar:
                self._clicar(filtrar)
            else:
                campo.send_keys(Keys.ENTER)
        else:
            campo.send_keys(Keys.ENTER)
        time.sleep(1)

        def recarregou(drv):
            if drv.execute_script(_JS_CARREGANDO):
                return False
            return drv.execute_script(
                "return ![...document.querySelectorAll('table tbody > tr')].some(tr => tr.dataset.imbraepVelho);")

        try:
            self._esperar(recarregou, 30)
        except TimeoutException:
            pass  # o mesmo resultado de antes: a tabela não mudou
        time.sleep(0.5)
        # fecha a janela do filtro, se ela ficou aberta
        modal = d.execute_script(_JS_MODAL)
        if modal and modal.find_elements(By.CSS_SELECTOR, "input#user_name"):
            cancelar = self._botao("cancelar", modal) or self._botao("fechar", modal)
            if cancelar:
                self._clicar(cancelar)
                time.sleep(0.5)

    # ---------- acompanhamento ----------
    def acompanhamento(self, nome: str) -> list[Matricula]:
        """As matrículas em andamento do aluno, com a Conclusão (%)."""
        d = self.driver

        def tabela(drv):
            return drv.execute_script(_JS_LINHAS_ACOMPANHAMENTO) is not None or bool(self._botao("filtrar"))

        self._abrir("/course-in-progress", tabela, "a tela de Acompanhamento", ["Acompanhamento"])
        achadas: list[list] = []
        for termo in termos_de_busca(nome):
            self._filtrar(termo, botao_modal=False)
            linhas = d.execute_script(_JS_LINHAS_ACOMPANHAMENTO) or []
            achadas = [l for l in linhas if mesmo_nome(nome, l[0])]
            if achadas:
                break
        matriculas = []
        for aluno, curso, status, n in achadas:
            matriculas.append(Matricula(aluno, curso, self._conclusao(n), status, "acompanhamento", n))
        return matriculas

    def _conclusao(self, n: int) -> str:
        d = self.driver
        linha = d.execute_script(_JS_LINHA_ACOMPANHAMENTO, n)
        if not linha:
            return "?"
        texto = d.execute_script(_JS_CONCLUSAO, linha)
        if texto is None:
            botoes = linha.find_elements(By.CSS_SELECTOR, "td:first-child button, td:first-child a")
            if not botoes:
                return "?"
            self._clicar(botoes[0])
            try:
                texto = self._esperar(lambda drv: drv.execute_script(
                    _JS_CONCLUSAO, drv.execute_script(_JS_LINHA_ACOMPANHAMENTO, n)), 15)
            except TimeoutException:
                self.salvar_diagnostico(f"Conclusão da linha {n + 1} do Acompanhamento")
                return "?"
        return texto

    # ---------- histórico e certificados ----------
    def historico(self, nome: str) -> list[Matricula]:
        """Os cursos concluídos do aluno em Histórico e Certificados."""
        d = self.driver

        def pronto(drv):
            return bool(self._botao("filtrar") or self._botao("alterar filtro"))

        self._abrir("/company-historial", pronto, "a tela de Histórico e Certificados",
                    ["Hist. e Certificados"])
        for termo in termos_de_busca(nome):
            self._filtrar(termo, botao_modal=True)
            linhas = d.execute_script(_JS_LINHAS_HISTORICO) or []
            achadas = [Matricula(a, c, "100%", "concluído", "historico", n) for a, c, n in linhas if mesmo_nome(nome, a)]
            if achadas:
                return achadas
        return []

    def baixar_certificado(self, m: Matricula, pasta: Path) -> Path:
        """Na tela de Histórico já filtrada: Certificado > assinatura > Download."""
        d = self.driver
        destino = pasta / nome_certificado(m.aluno, m.curso)
        linha = d.execute_script(_JS_LINHA_HISTORICO, m.linha)
        if not linha:
            raise self._erro(f"A linha de {m.aluno} sumiu da tela de Histórico.", "certificado")
        botao = next((b for b in linha.find_elements(By.CSS_SELECTOR, "button, a")
                      if normalizar(b.text) == "certificado"), None)
        self._clicar(botao)

        sem = self._esperar(lambda drv: self._botao("sem assinatura"), 30,
                            o_que="as opções \"Com assinatura\" / \"Sem assinatura\" do certificado")
        com = None
        fim = time.time() + 8  # a assinatura é carregada depois que a janela abre
        while time.time() < fim:
            com = self._botao("com assinatura")
            if com or not self.driver.execute_script(_JS_CARREGANDO) and time.time() > fim - 5:
                break
            time.sleep(0.5)
        if com:
            self.log(f"Gerando o certificado com assinatura de {m.aluno}...")
            self._clicar(com)
        else:
            self.log(f"Gerando o certificado sem assinatura de {m.aluno} (não há a opção com assinatura)...")
            self._clicar(sem)

        def gerou(drv):
            for a in drv.find_elements(By.CSS_SELECTOR, "a"):
                if a.is_displayed() and normalizar(a.text) == "download" and (a.get_attribute("href") or "").startswith("http"):
                    return ("link", a)
            texto = normalizar(drv.execute_script("return document.body.innerText") or "")
            if "certificado nao pode ser gerado" in texto:
                return ("bloqueado", drv.execute_script(
                    "const m = [...document.querySelectorAll('.modal-body')].find(e => e.offsetWidth && "
                    "/não pode ser gerado/i.test(e.innerText)); return m ? m.innerText.trim() : '';"))
            swal = drv.execute_script(_JS_SWAL)
            if swal and any(p in normalizar(swal["titulo"]) for p in ("erro", "error", "atencao")):
                return ("swal", swal)
            return False

        tipo, dado = self._esperar(gerou, 120, o_que="o botão \"Download\" do certificado")
        if tipo == "bloqueado":
            raise ErroPlataforma(" ".join((dado or "o certificado não pode ser gerado agora").split()))
        if tipo == "swal":
            self._responder_swal(confirmar=True)
            raise ErroPlataforma(f"{dado['titulo']} {dado['texto']}".strip())
        url = dado.get_attribute("href")
        pdf = self._baixar_pdf(url)
        if pdf:
            destino.write_bytes(pdf)
        else:  # baixa pelo próprio navegador
            antes = set(self.pasta_downloads.iterdir())
            janela, abas = d.current_window_handle, set(d.window_handles)
            self._clicar(dado)
            arquivo = self._esperar_download(antes, 90)
            for aba in d.window_handles:
                if aba not in abas:
                    d.switch_to.window(aba)
                    d.close()
            d.switch_to.window(janela)
            if not arquivo:
                raise self._erro("Cliquei em Download, mas o certificado não foi baixado.", f"download de {m.aluno}")
            destino.write_bytes(arquivo.read_bytes())
            try:
                arquivo.unlink()
            except OSError:
                pass
        self._fechar_modal()
        return destino

    def _fechar_modal(self):
        modal = self.driver.execute_script(_JS_MODAL)
        if modal:
            botao = self._botao("cancelar", modal) or self._botao("fechar", modal)
            if botao:
                self._clicar(botao)

    def _baixar_pdf(self, url: str) -> bytes | None:
        """Baixa o PDF do link de Download (pelo navegador, com a sessão; ou direto)."""
        for credenciais in ("include", "omit"):
            try:
                dados = self.driver.execute_async_script("""
                    const [url, cred, fim] = arguments;
                    fetch(url, {credentials: cred}).then(async r => {
                        if (!r.ok) return fim(null);
                        const b = new Uint8Array(await r.arrayBuffer());
                        let s = ''; for (let i = 0; i < b.length; i += 8192) s += String.fromCharCode(...b.subarray(i, i + 8192));
                        fim(btoa(s));
                    }).catch(() => fim(null));""", url, credenciais)
            except WebDriverException:
                dados = None
            if dados:
                pdf = base64.b64decode(dados)
                if pdf[:4] == b"%PDF":
                    return pdf
        try:
            with urllib.request.urlopen(url, timeout=60) as resposta:  # noqa: S310 (link da própria plataforma)
                pdf = resposta.read()
            if pdf[:4] == b"%PDF":
                return pdf
        except OSError:
            pass
        return None

    def _esperar_download(self, antes: set[Path], tempo: int) -> Path | None:
        """Espera um arquivo novo terminar de baixar (tamanho parado) e devolve o caminho."""
        fim = time.time() + tempo
        anterior: dict[Path, int] = {}
        while time.time() < fim:
            atual = {}
            try:
                for a in self.pasta_downloads.iterdir():
                    if a not in antes and a.suffix.lower() not in (".crdownload", ".tmp", ".partial"):
                        atual[a] = a.stat().st_size
                baixando = any(a.suffix.lower() == ".crdownload" for a in self.pasta_downloads.iterdir())
            except OSError:
                time.sleep(1)
                continue
            prontos = [a for a, tamanho in atual.items() if tamanho > 0 and anterior.get(a) == tamanho]
            if prontos and not baixando:
                return prontos[-1]
            anterior = atual
            time.sleep(1)
        return None
