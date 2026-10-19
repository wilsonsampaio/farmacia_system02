/* ============================================================
   FarmaSys — JavaScript geral
   Sem dependências externas (funciona offline na rede local)
   ============================================================ */
(function () {
  'use strict';

  /* ---------- utilidades ---------- */
  const $ = (sel, ctx) => (ctx || document).querySelector(sel);
  const $$ = (sel, ctx) => Array.from((ctx || document).querySelectorAll(sel));

  window.FS = {
    $, $$,
    moeda(v) {
      const n = Number(v || 0);
      return n.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
    },
    numero(v) {
      return Number(v || 0).toLocaleString('pt-BR');
    },
    /* aviso rápido (contêiner próprio, fixo na tela) */
    toast(msg, tipo) {
      let box = document.getElementById('fs-toasts');
      if (!box) {
        box = document.createElement('div');
        box.id = 'fs-toasts';
        document.body.appendChild(box);
      }
      const div = document.createElement('div');
      div.className = 'fs-toast ' + (tipo || 'info');
      div.innerHTML =
        '<svg class="ic" width="18" height="18"><use href="#i-' +
        (tipo === 'erro' ? 'excluir' : tipo === 'sucesso' ? 'check' : 'alerta') +
        '"/></svg><span></span>';
      div.querySelector('span').textContent = msg;
      box.appendChild(div);
      setTimeout(() => div.classList.add('show'), 20);
      setTimeout(() => {
        div.classList.remove('show');
        setTimeout(() => div.remove(), 400);
      }, 4200);
    },
    /* confirmação em modal */
    confirmar(texto, titulo) {
      return new Promise((resolve) => {
        const m = document.createElement('div');
        m.className = 'modal';
        m.innerHTML =
          '<div class="modal-dialogo modal-sm">' +
          '<div class="modal-cab"><h3>' + (titulo || 'Confirmar') + '</h3>' +
          '<button class="fecha-modal" data-n="0" aria-label="Fechar">×</button></div>' +
          '<div class="modal-corpo"><p style="margin:0">' + texto + '</p></div>' +
          '<div class="modal-acoes">' +
          '<button class="btn btn-ghost" data-n="0">Cancelar</button>' +
          '<button class="btn btn-primario" data-n="1">Confirmar</button>' +
          '</div></div>';
        document.body.appendChild(m);
        const encerra = (ok) => { m.remove(); resolve(ok); };
        m.addEventListener('click', (e) => {
          if (e.target === m) return encerra(false);
          const b = e.target.closest('button[data-n]');
          if (b) encerra(b.dataset.n === '1');
        });
      });
    },
  };

  /* ---------- modais genéricos (data-abre-modal / data-fecha) ---------- */
  function abrirModal(id) {
    const m = document.getElementById(id);
    if (!m) return;
    m.hidden = false;
    m.classList.add('show');
    const foco = m.querySelector('input[autofocus], textarea[autofocus], .btn-primario, button');
    if (foco) setTimeout(() => foco.focus(), 60);
  }
  function fecharModal(m) {
    if (!m) return;
    m.classList.remove('show');
    m.hidden = true;
  }
  document.addEventListener('click', (e) => {
    const abre = e.target.closest('[data-abre-modal]');
    if (abre) { abrirModal(abre.dataset.abreModal); return; }
    const fecha = e.target.closest('.modal [data-fecha], .modal .fecha-modal');
    if (fecha) { fecharModal(fecha.closest('.modal')); return; }
    /* clicar no fundo do modal também fecha */
    if (e.target.classList && e.target.classList.contains('modal')) fecharModal(e.target);
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      const abertos = $$('.modal:not([hidden])');
      if (abertos.length) fecharModal(abertos[abertos.length - 1]);
    }
  });
  window.FS.abrirModal = abrirModal;
  window.FS.fecharModal = fecharModal;

  /* ---------- sidebar (salvar preferência) ---------- */
  const toggle = $('[data-toggle-sidebar]');
  const sidebar = $('#sidebar');
  if (toggle && sidebar) {
    if (localStorage.getItem('fs-sidebar') === 'off') {
      sidebar.classList.add('off');
      document.body.classList.add('sidebar-off');
    }
    toggle.addEventListener('click', () => {
      const off = sidebar.classList.toggle('off');
      document.body.classList.toggle('sidebar-off', off);
      localStorage.setItem('fs-sidebar', off ? 'off' : 'on');
    });
  }

  /* ---------- tema claro/escuro ---------- */
  /* o tema é o atributo data-tema do <html> (o CSS alterna os ícones .tema-claro/.tema-escuro).
     ATENÇÃO: nunca usar '[data-tema]' como seletor de botão — ele casa com o próprio <html>. */
  const btnTema = $('#btnTema');
  const aplicaTema = (salva) => {
    if (salva) localStorage.setItem('fs-tema', salva);
    document.documentElement.setAttribute('data-tema', salva || 'claro');
  };
  {
    const salvo = localStorage.getItem('fs-tema');
    if (salvo === 'escuro' || salvo === 'claro') aplicaTema(salvo);
  }
  if (btnTema) {
    btnTema.addEventListener('click', () => {
      const atual = document.documentElement.getAttribute('data-tema') === 'escuro' ? 'claro' : 'escuro';
      aplicaTema(atual);
      btnTema.title = atual === 'escuro' ? 'Modo claro' : 'Modo escuro';
    });
    btnTema.title = document.documentElement.getAttribute('data-tema') === 'escuro' ? 'Modo claro' : 'Modo escuro';
  }

  /* ---------- menu do usuário (topo) ---------- */
  $$('[data-dropdown]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const alvo = $(btn.dataset.dropdown);
      if (!alvo) return;
      const aberto = alvo.classList.toggle('show');
      $$('[data-dropdown-menu]').forEach((m) => { if (m !== alvo) m.classList.remove('show'); });
      if (!aberto) return;
      const fecha = (ev) => {
        if (!alvo.contains(ev.target) && ev.target !== btn) {
          alvo.classList.remove('show');
          document.removeEventListener('click', fecha);
        }
      };
      document.addEventListener('click', fecha);
    });
  });

  /* ---------- botões que abrem um formulário oculto (ex.: sair) ---------- */
  $$('form[data-simples]').forEach((f) => {
    f.addEventListener('submit', (e) => {
      if (f.dataset.confirmar && !confirm(f.dataset.confirmar)) e.preventDefault();
    });
  });

  /* ---------- confirmações em links/botões ---------- */
  document.addEventListener('click', async (e) => {
    const el = e.target.closest('[data-confirm]');
    if (!el) return;
    e.preventDefault();
    const ok = await FS.confirmar(el.dataset.confirm, el.dataset.titulo);
    if (!ok) return;
    if (el.tagName === 'A') { window.location.href = el.href; return; }
    const form = el.closest('form');
    if (form) form.submit();
  });

  /* ---------- abas (data-abas) ---------- */
  $$('[data-abas]').forEach((wrap) => {
    const botoes = $$('[data-aba]', wrap);
    const paineis = $$('[data-aba-painel], [data-painel]', wrap.parentElement || document);
    const temPainel = (nome) => paineis.some((p) => (p.dataset.abaPainel || p.dataset.painel) === nome);
    const mostra = (nome) => {
      botoes.forEach((b) => b.classList.toggle('ativo', b.dataset.aba === nome));
      paineis.forEach((p) => {
        const chave = p.dataset.abaPainel || p.dataset.painel;
        if (chave === nome) p.hidden = false;
        else if (botoes.some((b) => b.dataset.aba === chave)) p.hidden = true;
      });
      localStorage.setItem('fs-aba-' + (wrap.dataset.abas || window.location.pathname), nome);
    };
    botoes.forEach((b) => b.addEventListener('click', () => {
      if (b.dataset.abaUrl) { window.location.href = b.dataset.abaUrl; return; }
      /* abas controladas pelo servidor (?aba=): navega em vez de alternar */
      if (!temPainel(b.dataset.aba) && wrap.dataset.abasServidor !== undefined) {
        const u = new URL(window.location.href);
        u.searchParams.set('aba', b.dataset.aba);
        window.location.href = u.toString();
        return;
      }
      mostra(b.dataset.aba);
    }));
    const salvo = localStorage.getItem('fs-aba-' + (wrap.dataset.abas || window.location.pathname));
    const inicial = (botoes.find((b) => b.dataset.aba === salvo) ? salvo
      : (botoes.find((b) => b.classList.contains('ativo')) || botoes[0] || {}).dataset);
    if (inicial) mostra(typeof inicial === 'string' ? inicial : inicial.aba);
  });

  /* ---------- máscaras de digitação ---------- */
  function mascara(sel, fn) {
    $$(sel).forEach((el) => {
      el.addEventListener('input', () => {
        const antes = el.value;
        el.value = fn(el.value.replace(/\D/g, ''));
        if (el.value === antes && antes !== '') el.value = fn(antes.replace(/\D/g, ''));
      });
      if (el.value) el.dispatchEvent(new Event('input'));
    });
  }
  const M = {
    cpf(v) {
      v = v.slice(0, 11);
      return v.replace(/(\d{3})(\d)/, '$1.$2')
        .replace(/(\d{3})(\d)/, '$1.$2')
        .replace(/(\d{3})(\d{1,2})$/, '$1-$2');
    },
    cnpj(v) {
      v = v.slice(0, 14);
      return v.replace(/(\d{2})(\d)/, '$1.$2')
        .replace(/(\d{3})(\d)/, '$1.$2')
        .replace(/(\d{3})(\d)/, '$1/$2')
        .replace(/(\d{4})(\d{1,2})$/, '$1-$2');
    },
    fone(v) {
      v = v.slice(0, 11);
      if (v.length <= 10) {
        return v.replace(/(\d{2})(\d)/, '($1) $2').replace(/(\d{4})(\d)/, '$1-$2');
      }
      return v.replace(/(\d{2})(\d)/, '($1) $2').replace(/(\d{5})(\d)/, '$1-$2');
    },
    cep(v) {
      v = v.slice(0, 8);
      return v.replace(/(\d{5})(\d)/, '$1-$2');
    },
    inteiro(v) { return v.replace(/\D/g, '').slice(0, 9); },
  };
  mascara('[data-cpf]', M.cpf);
  mascara('[data-cnpj]', M.cnpj);
  mascara('[data-fone]', M.fone);
  mascara('[data-cep]', M.cep);
  mascara('[data-numeros]', M.inteiro);
  mascara('[data-lote]', (v) => v.toUpperCase());

  /* campos em dinheiro: aceitam vírgula e formatam ao sair */
  $$('[data-moeda]').forEach((el) => {
    const paraTexto = (n) => n.toFixed(2).replace('.', ',').replace(/\B(?=(\d{3})+(?!\d)(,))/g, '.');
    const paraNumero = (t) => {
      const limpo = String(t).replace(/[^\d,.-]/g, '').replace(/\./g, '').replace(',', '.');
      return isNaN(parseFloat(limpo)) ? 0 : parseFloat(limpo);
    };
    el.addEventListener('blur', () => { el.value = paraTexto(paraNumero(el.value)); });
    el.addEventListener('input', () => {
      let v = el.value.replace(/[^\d,]/g, '');
      const p = v.split(',');
      if (p.length > 2) v = p[0] + ',' + p.slice(1).join('').slice(0, 2);
      else if (p.length === 2) v = p[0] + ',' + p[1].slice(0, 2);
      el.value = v;
    });
    if (el.value) el.value = paraTexto(paraNumero(el.value));
  });

  /* validação de CPF/CNPJ no envio do formulário */
  document.addEventListener('submit', (e) => {
    $$('[data-cpf]').forEach((el) => {
      const v = el.value.replace(/\D/g, '');
      if (v && v.length !== 11) {
        el.classList.add('invalido');
        FS.toast('CPF inválido: deve ter 11 dígitos', 'erro');
        e.preventDefault();
      }
    });
    $$('[data-cnpj]').forEach((el) => {
      const v = el.value.replace(/\D/g, '');
      if (v && v.length !== 14) {
        el.classList.add('invalido');
        FS.toast('CNPJ inválido: deve ter 14 dígitos', 'erro');
        e.preventDefault();
      }
    });
  });

  /* ---------- prévia de foto ---------- */
  $$('input[type="file"][data-preview]').forEach((input) => {
    const alvo = $(input.dataset.preview);
    if (!alvo) return;
    input.addEventListener('change', () => {
      const f = input.files && input.files[0];
      if (!f) return;
      const r = new FileReader();
      r.onload = () => {
        alvo.innerHTML = '<img src="' + r.result + '" alt="">';
        alvo.classList.add('tem-foto');
      };
      r.readAsDataURL(f);
    });
  });

  /* ---------- cálculo de margem no formulário de produto ---------- */
  const precoCusto = $('#preco_custo'), precoVenda = $('#preco_venda'), margem = $('#margem');
  function calculaMargem() {
    if (!precoCusto || !precoVenda || !margem) return;
    const c = parseFloat(precoCusto.value.replace(',', '.')) || 0;
    const v = parseFloat(precoVenda.value.replace(',', '.')) || 0;
    if (c <= 0 || v <= 0) { margem.value = ''; return; }
    margem.value = (((v - c) / c) * 100).toFixed(1).replace('.', ',') + ' %';
  }
  if (precoCusto) {
    precoCusto.addEventListener('input', calculaMargem);
    precoVenda.addEventListener('input', calculaMargem);
    calculaMargem();
  }

  /* ---------- cálculo de diferença no inventário ---------- */
  $$('tr[data-inventario]').forEach((tr) => {
    const cont = $('[data-contagem]', tr);
    const dif = $('[data-diferenca]', tr);
    if (!cont || !dif) return;
    const sistema = Number(tr.dataset.sistema || 0);
    cont.addEventListener('input', () => {
      const c = cont.value === '' ? null : Number(cont.value);
      if (c === null) { dif.textContent = '—'; dif.className = 'badge'; return; }
      const d = c - sistema;
      dif.textContent = (d > 0 ? '+' : '') + d;
      dif.className = 'badge ' + (d === 0 ? 'ok' : d < 0 ? 'alerta' : 'info');
    });
  });

  /* ---------- exportação CSV (botão com data-url-base) ---------- */
  const btnCsv = $('#btnExportCsv');
  if (btnCsv) {
    btnCsv.addEventListener('click', () => {
      const params = new URLSearchParams(window.location.search);
      btnCsv.disabled = true;
      btnCsv.textContent = 'Gerando...';
      /* o download precisa navegar, então abrimos a URL com os filtros atuais */
      const url = btnCsv.dataset.urlBase + '?' + params.toString();
      window.location.href = url;
      setTimeout(() => { btnCsv.disabled = false; btnCsv.textContent = 'Exportar CSV'; }, 2500);
    });
  }

  /* ---------- busca de produto na baixa manual ---------- */
  const buscaBaixa = $('#buscaProdutoBaixa');
  if (buscaBaixa) {
    const resultado = $('#resultadoBuscaBaixa');
    const id = $('#produto_baixa_id');
    let t;
    buscaBaixa.addEventListener('input', () => {
      clearTimeout(t);
      const q = buscaBaixa.value.trim();
      if (q.length < 2) { resultado.innerHTML = ''; id.value = ''; return; }
      t = setTimeout(async () => {
        try {
          const r = await fetch('/produtos/api/buscar?q=' + encodeURIComponent(q));
          const dados = await r.json();
          id.value = '';
          if (!dados.length) { resultado.innerHTML = '<p style="margin:6px 0;color:var(--texto-suave)">Nenhum produto encontrado.</p>'; return; }
          resultado.innerHTML = dados.map((p) =>
            '<button type="button" data-id="' + p.id + '" class="linha-busca">' +
            '<strong>' + p.nome + '</strong>' +
            '<small>' + (p.principio_ativo || '—') + ' · ' + (p.apresentacao || '—') + '</small>' +
            '<span>Estoque: ' + p.estoque + '</span></button>'
          ).join('');
        } catch (e) { /* rede */ }
      }, 220);
    });
    resultado.addEventListener('click', (e) => {
      const b = e.target.closest('button[data-id]');
      if (!b) return;
      const texto = b.querySelector('strong').textContent;
      buscaBaixa.value = texto;
      id.value = b.dataset.id;
      resultado.innerHTML = '';
    });
  }

  /* ---------- linhas dinâmicas na entrada de estoque ---------- */
  const btnAddLinha = $('#btnAddLinha');
  if (btnAddLinha) {
    let indice = $$('tr[data-linha-produto]').length;
    btnAddLinha.addEventListener('click', () => {
      const modelo = $('tr[data-linha-produto]');
      if (!modelo) return;
      const nova = modelo.cloneNode(true);
      nova.querySelectorAll('input, select').forEach((c) => {
        c.name = c.name ? c.name.replace(/\[\d+\]/, '[' + indice + ']') : c.name;
        if (c.type !== 'hidden') c.value = '';
        c.required = c.hasAttribute('data-obrigatorio') ? true : false;
      });
      indice++;
      $('tbody', modelo.closest('table')).appendChild(nova);
      const primeiro = nova.querySelector('input, select');
      if (primeiro) primeiro.focus();
    });
  }

  /* ---------- busca global (Ctrl + K) ---------- */
  const global = $('#buscaGlobal');
  if (global) {
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        global.focus();
        global.select();
      }
    });
  }

  /* ---------- fade/slide em itens com [data-fade] ---------- */
  $$('[data-fade]').forEach((el, i) => {
    el.style.opacity = '0';
    el.style.transform = 'translateY(8px)';
    setTimeout(() => {
      el.style.transition = 'opacity .4s ease, transform .4s ease';
      el.style.opacity = '1';
      el.style.transform = 'none';
    }, 30 * Math.min(i, 12));
  });

  /* ---------- avisos de sessão ---------- */
  setInterval(async () => {
    try {
      const r = await fetch('/api/verificar-sessao');
      const j = await r.json();
      if (!j.valida && !window.location.pathname.startsWith('/login')) {
        FS.toast('Sua sessão expirou. Entre novamente.', 'erro');
        setTimeout(() => { window.location.href = '/login'; }, 1400);
      }
    } catch (e) { /* servidor pode estar reiniciando */ }
  }, 60000);

  /* ---------- tabela: realce da linha em foco ---------- */
  $$('table tbody tr').forEach((tr) => {
    tr.addEventListener('click', (e) => {
      if (e.target.closest('a, button, input, select')) return;
      const link = tr.querySelector('a[href]');
      if (link) window.location.href = link.href;
    });
  });
})();
