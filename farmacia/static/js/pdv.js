/* ============================================================
   FarmaSys — PDV (Ponto de Venda)
   Carrinho, busca, pagamento e finalização da venda
   ============================================================ */
(function () {
  'use strict';

  const $ = (s, c) => (c || document).querySelector(s);
  const $$ = (s, c) => Array.from((c || document).querySelectorAll(s));

  const pdv = $('#pdv');
  if (!pdv) return; /* só roda na tela do PDV */

  const CHAVE = 'fs-pdv-carrinho-' + (pdv.dataset.terminal || 'PDV');

  /* ---------------- estado ---------------- */
  const estado = {
    itens: [],            /* {produto_id, nome, apresentacao, preco, estoque, qtd, desconto} */
    cliente: null,        /* {id, nome, limite_credito, saldo_credito} */
    descontoTotal: 0,     /* em reais */
    pagamentos: [],       /* {forma, valor, parcelas} */
    formaSelecionada: 'dinheiro',
    modoDesconto: 'valor',
    descontoItemIndice: null,
  };

  try {
    const salvo = JSON.parse(localStorage.getItem(CHAVE) || 'null');
    if (salvo && Array.isArray(salvo.itens) && salvo.itens.length) {
      estado.itens = salvo.itens;
      estado.descontoTotal = salvo.descontoTotal || 0;
      if (salvo.cliente) {
        estado.cliente = salvo.cliente;
        $('#chipCliente').textContent = salvo.cliente.nome;
        $('#clienteId').value = salvo.cliente.id;
      }
    }
  } catch (e) { /* estado corrompido: começa do zero */ }

  function salvar() {
    localStorage.setItem(CHAVE, JSON.stringify({
      itens: estado.itens, descontoTotal: estado.descontoTotal, cliente: estado.cliente,
    }));
  }

  /* ---------------- utilidades ---------------- */
  function brl(v) { return FS.moeda(v); }
  function num(v) {
    if (typeof v === 'number') return v;
    const t = String(v || '').trim().replace(/[^\d,.-]/g, '').replace(/\./g, '').replace(',', '.');
    const n = parseFloat(t);
    return isNaN(n) ? 0 : n;
  }

  /* ---------------- relógio ---------------- */
  const relogio = $('#relogio');
  function tick() {
    if (!relogio) return;
    relogio.textContent = new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  }
  tick();
  setInterval(tick, 20000);

  /* ---------------- modais ---------------- */
  function abrir(id) {
    const m = $('#' + id);
    if (!m) return;
    m.hidden = false;
    m.classList.add('show');
    const foco = m.querySelector('input[autofocus], button.btn-primario');
    if (foco) setTimeout(() => foco.focus(), 60);
  }
  function fechar(id) {
    const m = $('#' + id);
    if (!m) return;
    m.classList.remove('show');
    m.hidden = true;
  }
  $$('[data-abre-modal]').forEach((b) => b.addEventListener('click', () => abrir(b.dataset.abreModal)));
  document.addEventListener('click', (e) => {
    const f = e.target.closest('.modal [data-fecha], .modal .fecha-modal');
    if (!f) return;
    const m = f.closest('.modal');
    if (m) { m.classList.remove('show'); m.hidden = true; }
  });

  /* segmentado R$ / % */
  $$('[data-segmentado] button').forEach((b) => {
    b.addEventListener('click', () => {
      $$('[data-segmentado] button').forEach((x) => x.classList.remove('ativo'));
      b.classList.add('ativo');
      estado.modoDesconto = b.dataset.valor;
      atualizaPreviaDesconto();
    });
  });

  /* ---------------- busca de produto ---------------- */
  const campoBusca = $('#buscaProduto');
  const resultados = $('#resultadosBuscaProduto');
  let tempoBusca;

  async function buscarProdutos(termo) {
    try {
      const r = await fetch('/pdv/buscar?codigo=' + encodeURIComponent(termo));
      if (!r.ok) throw new Error();
      return await r.json();
    } catch (e) {
      FS.toast('Falha ao buscar produtos. Verifique a conexão.', 'erro');
      return { produto: null, resultados: [] };
    }
  }

  function pintaResultados(dados) {
    if (dados.produto) { adiciona(dados.produto); campoBusca.value = ''; resultados.innerHTML = dica(); return; }
    if (!dados.resultados.length) {
      resultados.innerHTML = '<p class="pdv-dica">Nenhum medicamento encontrado para “' + campoBusca.value + '”.</p>';
      return;
    }
    resultados.innerHTML = dados.resultados.map((p) =>
      '<button type="button" class="pdv-item-busca" data-id="' + p.id + '">' +
      '<span class="pdv-item-nome"><strong>' + p.nome + '</strong>' +
      '<small>' + (p.principio_ativo || '—') + ' · ' + (p.apresentacao || '') +
      (p.laboratorio ? ' · ' + p.laboratorio : '') + '</small></span>' +
      '<span class="pdv-item-preco">' + brl(p.preco_venda) + '</span>' +
      '<span class="pdv-item-estoque ' + (p.estoque > 0 ? '' : 'sem') + '">' +
      (p.estoque > 0 ? p.estoque + ' ' + (p.unidade || 'un') : 'Sem estoque') + '</span>' +
      '</button>'
    ).join('');
  }

  function dica() {
    return '<p class="pdv-dica">Comece a digitar ou passe o leitor de código de barras para buscar medicamentos.</p>';
  }

  campoBusca.addEventListener('input', () => {
    clearTimeout(tempoBusca);
    const t = campoBusca.value.trim();
    if (t.length < 2) { resultados.innerHTML = dica(); return; }
    tempoBusca = setTimeout(async () => pintaResultados(await buscarProdutos(t)), 220);
  });

  campoBusca.addEventListener('keydown', async (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      const primeiro = resultados.querySelector('.pdv-item-busca');
      if (primeiro && !campoBusca.value.trim().match(/^\d{6,14}$/)) primeiro.click();
      else pintaResultados(await buscarProdutos(campoBusca.value.trim()));
    }
    if (e.key === 'Escape') { campoBusca.value = ''; resultados.innerHTML = dica(); }
  });

  $('#btnBuscar').addEventListener('click', async () => {
    if (campoBusca.value.trim()) pintaResultados(await buscarProdutos(campoBusca.value.trim()));
    campoBusca.focus();
  });

  resultados.addEventListener('click', async (e) => {
    const b = e.target.closest('.pdv-item-busca');
    if (!b) return;
    const id = b.dataset.id;
    const r = await buscarProdutos(campoBusca.value.trim());
    const p = (r.resultados || []).find((x) => String(x.id) === id);
    if (p) adiciona(p);
    campoBusca.value = '';
    resultados.innerHTML = dica();
    campoBusca.focus();
  });

  /* ---------------- carrinho ---------------- */
  function adiciona(p) {
    if (!p || !p.estoque || p.estoque <= 0) {
      FS.toast('Produto sem estoque disponível.', 'erro');
      return;
    }
    const existente = estado.itens.find((i) => i.produto_id === p.id);
    if (existente) {
      if (existente.qtd + 1 > p.estoque) {
        FS.toast('Estoque insuficiente: restam ' + p.estoque + ' ' + (p.unidade || 'un') + '.', 'erro');
        return;
      }
      existente.qtd += 1;
    } else {
      estado.itens.push({
        produto_id: p.id,
        nome: p.nome,
        apresentacao: p.apresentacao || '',
        preco: parseFloat(p.preco_venda) || 0,
        estoque: parseInt(p.estoque, 10) || 0,
        unidade: p.unidade || 'un',
        qtd: 1,
        desconto: 0,
      });
    }
    salvar();
    pintaCarrinho();
    FS.toast(p.nome + ' adicionado.', 'sucesso');
  }

  function subtotalItens() {
    return estado.itens.reduce((s, i) => s + i.preco * i.qtd, 0);
  }
  function descontoItens() {
    return estado.itens.reduce((s, i) => s + (i.desconto || 0), 0);
  }
  function totalVenda() {
    const base = subtotalItens() - descontoItens();
    return Math.max(0, base - (estado.descontoTotal || 0));
  }

  function pintaCarrinho() {
    const corpo = $('#corpoCarrinho');
    if (!estado.itens.length) {
      corpo.innerHTML =
        '<tr class="linha-vazia"><td colspan="7"><div class="carrinho-vazio">' +
        '<svg class="ic ic-lg"><use href="#i-pill"/></svg>' +
        '<p><strong>Carrinho vazio</strong></p>' +
        '<p>Busque o medicamento acima ou passe o código de barras.<br>' +
        'Atalhos: <kbd>F2</kbd> buscar · <kbd>F4</kbd> cliente · <kbd>F8</kbd> desconto · ' +
        '<kbd>F9</kbd> pagamento · <kbd>ESC</kbd> limpar</p></div></td></tr>';
    } else {
      corpo.innerHTML = estado.itens.map((i, idx) =>
        '<tr>' +
        '<td class="c-item">' + (idx + 1) + '</td>' +
        '<td class="c-desc"><strong>' + i.nome + '</strong>' +
        (i.apresentacao ? '<small>' + i.apresentacao + '</small>' : '') + '</td>' +
        '<td class="c-qtd">' +
        '<button type="button" class="qtd-btn" data-dim="' + idx + '">−</button>' +
        '<input type="number" class="qtd-input" min="1" max="' + i.estoque + '" value="' + i.qtd + '" data-qtd="' + idx + '">' +
        '<button type="button" class="qtd-btn" data-inc="' + idx + '">+</button></td>' +
        '<td class="c-unit">' + brl(i.preco) + '</td>' +
        '<td class="c-desc-vl">' +
        (i.desconto > 0 ? '<span class="texto-ok">−' + brl(i.desconto) + '</span>' :
          '<button type="button" class="link-suave" data-desc-item="' + idx + '">dar desconto</button>') + '</td>' +
        '<td class="c-total">' + brl(i.preco * i.qtd - (i.desconto || 0)) + '</td>' +
        '<td class="c-acao"><button type="button" class="btn-x" data-remover="' + idx + '" title="Remover">×</button></td>' +
        '</tr>'
      ).join('');
    }
    $('#resumoItens').textContent = estado.itens.length;
    $('#resumoSubtotal').textContent = brl(subtotalItens());
    $('#resumoDesconto').textContent = '− ' + brl(descontoItens() + estado.descontoTotal);
    $('#resumoTotal').textContent = brl(totalVenda());
    $('#totalGrande').textContent = brl(totalVenda());
    $('#totalQtd').textContent = estado.itens.length + ' item(s)';
  }

  $('#corpoCarrinho').addEventListener('click', (e) => {
    const alvo = e.target;
    const inc = alvo.closest('[data-inc]');
    const dim = alvo.closest('[data-dim]');
    const rem = alvo.closest('[data-remover]');
    const desc = alvo.closest('[data-desc-item]');
    if (inc) {
      const i = estado.itens[+inc.dataset.inc];
      if (i.qtd + 1 > i.estoque) { FS.toast('Estoque insuficiente (máx. ' + i.estoque + ').', 'erro'); return; }
      i.qtd += 1;
    } else if (dim) {
      const i = estado.itens[+dim.dataset.dim];
      i.qtd -= 1;
      if (i.qtd < 1) { estado.itens.splice(estado.itens.indexOf(i), 1); }
    } else if (rem) {
      estado.itens.splice(+rem.dataset.remover, 1);
    } else if (desc) {
      estado.descontoItemIndice = +desc.dataset.descItem;
      const i = estado.itens[estado.descontoItemIndice];
      $('#tituloDesconto').textContent = 'Desconto no item';
      $('#descricaoDesconto').textContent = i.nome + ' — subtotal do item: ' + brl(i.preco * i.qtd);
      $('#valorDesconto').value = '';
      atualizaPreviaDesconto();
      abrir('modalDesconto');
      return;
    } else return;
    salvar();
    pintaCarrinho();
  });

  $('#corpoCarrinho').addEventListener('change', (e) => {
    const inp = e.target.closest('[data-qtd]');
    if (!inp) return;
    const i = estado.itens[+inp.dataset.qtd];
    let q = parseInt(inp.value, 10) || 1;
    if (q > i.estoque) { q = i.estoque; FS.toast('Quantidade limitada ao estoque (' + i.estoque + ').', 'erro'); }
    if (q < 1) q = 1;
    i.qtd = q;
    salvar();
    pintaCarrinho();
  });

  $('#btnLimpar').addEventListener('click', async () => {
    if (!estado.itens.length) return;
    if (!(await FS.confirmar('Limpar todos os itens do carrinho?', 'Limpar carrinho'))) return;
    estado.itens = [];
    estado.descontoTotal = 0;
    salvar();
    pintaCarrinho();
  });

  /* ---------------- descontos ---------------- */
  function atualizaPreviaDesconto() {
    const v = num($('#valorDesconto').value);
    let novo = totalVenda();
    if (estado.descontoItemIndice !== null) {
      const i = estado.itens[estado.descontoItemIndice];
      const base = i.preco * i.qtd;
      const d = estado.modoDesconto === 'percentual' ? base * v / 100 : v;
      novo = totalVenda() - i.desconto + Math.min(Math.max(d, 0), base);
    } else {
      const base = subtotalItens() - descontoItens();
      const d = estado.modoDesconto === 'percentual' ? base * v / 100 : v;
      novo = Math.max(0, base - Math.min(Math.max(d, 0), base));
    }
    $('#totalAposDesconto').textContent = brl(novo);
  }
  $('#valorDesconto').addEventListener('input', atualizaPreviaDesconto);

  $('#btnDescontoItem').addEventListener('click', () => {
    if (!estado.itens.length) { FS.toast('Adicione itens antes de dar desconto.', 'erro'); return; }
    estado.descontoItemIndice = 0;
    const i = estado.itens[0];
    $('#tituloDesconto').textContent = 'Desconto no item (primeiro item)';
    $('#descricaoDesconto').textContent = i.nome + ' — subtotal do item: ' + brl(i.preco * i.qtd);
    $('#valorDesconto').value = '';
    atualizaPreviaDesconto();
    abrir('modalDesconto');
  });

  $('#btnDescontoTotal').addEventListener('click', () => {
    if (!estado.itens.length) { FS.toast('Carrinho vazio.', 'erro'); return; }
    estado.descontoItemIndice = null;
    $('#tituloDesconto').textContent = 'Desconto total da venda';
    $('#descricaoDesconto').textContent = 'Subtotal: ' + brl(subtotalItens() - descontoItens());
    $('#valorDesconto').value = '';
    atualizaPreviaDesconto();
    abrir('modalDesconto');
  });

  $('#btnAplicarDesconto').addEventListener('click', () => {
    const v = num($('#valorDesconto').value);
    if (v < 0) { FS.toast('Valor inválido.', 'erro'); return; }
    if (estado.descontoItemIndice !== null) {
      const i = estado.itens[estado.descontoItemIndice];
      const base = i.preco * i.qtd;
      const d = estado.modoDesconto === 'percentual' ? base * v / 100 : v;
      i.desconto = Math.min(Math.max(d, 0), base);
    } else {
      const base = subtotalItens() - descontoItens();
      const d = estado.modoDesconto === 'percentual' ? base * v / 100 : v;
      estado.descontoTotal = Math.min(Math.max(d, 0), base);
    }
    estado.descontoItemIndice = null;
    salvar();
    pintaCarrinho();
    fechar('modalDesconto');
    FS.toast('Desconto aplicado.', 'sucesso');
  });

  /* ---------------- cliente ---------------- */
  let tempoCliente;
  $('#btnCliente').addEventListener('click', () => {
    abrir('modalCliente');
    setTimeout(() => $('#buscaCliente').focus(), 80);
  });

  $('#buscaCliente').addEventListener('input', () => {
    clearTimeout(tempoCliente);
    const t = $('#buscaCliente').value.trim();
    const box = $('#resultadosCliente');
    if (t.length < 2) { box.innerHTML = ''; return; }
    tempoCliente = setTimeout(async () => {
      try {
        const r = await fetch('/clientes/api/buscar?q=' + encodeURIComponent(t));
        const lista = await r.json();
        box.innerHTML = (Array.isArray(lista) ? lista : lista.clientes || []).map((c) =>
          '<button type="button" class="linha-busca" data-cliente="' + c.id + '" data-nome="' + c.nome + '" ' +
          'data-limite="' + (c.limite_credito || 0) + '" data-saldo="' + (c.saldo_credito || 0) + '">' +
          '<strong>' + c.nome + '</strong><small>' + (c.cpf || '') + ' ' + (c.celular || '') + '</small>' +
          '<span>' + (c.saldo_credito > 0 ? 'Deve ' + brl(c.saldo_credito) : 'Em dia') + '</span></button>'
        ).join('') || '<p class="texto-suave">Nenhum cliente encontrado.</p>';
      } catch (e) { FS.toast('Falha ao buscar clientes.', 'erro'); }
    }, 220);
  });

  $('#resultadosCliente').addEventListener('click', (e) => {
    const b = e.target.closest('[data-cliente]');
    if (!b) return;
    selecionaCliente({ id: b.dataset.cliente, nome: b.dataset.nome,
      limite_credito: b.dataset.limite, saldo_credito: b.dataset.saldo });
    fechar('modalCliente');
  });

  function selecionaCliente(c) {
    estado.cliente = c;
    $('#clienteId').value = c.id;
    $('#chipCliente').textContent = c.nome;
    salvar();
    FS.toast('Cliente ' + c.nome + ' selecionado.', 'sucesso');
  }

  $('#btnSemCliente').addEventListener('click', () => {
    estado.cliente = null;
    $('#clienteId').value = '';
    $('#chipCliente').textContent = 'Consumidor';
    salvar();
    fechar('modalCliente');
  });

  $('#btnSalvarCliente').addEventListener('click', async () => {
    const nome = $('#novoClienteNome').value.trim();
    if (nome.length < 3) { FS.toast('Informe o nome do cliente.', 'erro'); return; }
    try {
      const r = await fetch('/pdv/cliente', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nome, cpf: $('#novoClienteCpf').value, celular: $('#novoClienteCelular').value }),
      });
      const j = await r.json();
      if (!r.ok) { FS.toast(j.erro || 'Erro ao cadastrar.', 'erro'); return; }
      selecionaCliente(j.cliente);
      $('#novoClienteNome').value = '';
      $('#novoClienteCpf').value = '';
      $('#novoClienteCelular').value = '';
      fechar('modalCliente');
    } catch (e) { FS.toast('Falha de conexão.', 'erro'); }
  });

  /* observação rápida */
  $('#btnObservacao').addEventListener('click', () => {
    abrir('modalPagamento');
    setTimeout(() => $('#pagObservacao').focus(), 100);
  });

  /* ---------------- pagamento ---------------- */
  function pintaFormas() {
    $$('.forma-btn, .forma-pag').forEach((b) => {
      b.classList.toggle('ativo', b.dataset.forma === estado.formaSelecionada);
    });
    $('#campoParcelas').hidden = !(estado.formaSelecionada === 'credito' || estado.formaSelecionada === 'fiado');
  }

  $$('.forma-btn, .forma-pag').forEach((b) => {
    b.addEventListener('click', () => {
      const forma = b.dataset.forma;
      if (b.dataset.exigeCliente && !estado.cliente) {
        FS.toast('Selecione um cliente para vender na ficha.', 'erro');
        abrir('modalCliente');
        return;
      }
      estado.formaSelecionada = forma;
      pintaFormas();
      const campo = $('#pagValor');
      if (forma === 'dinheiro' || forma === 'pix') {
        campo.value = (totalVenda() - somaPagamentos()).toFixed(2).replace('.', ',');
      }
      campo.focus();
    });
  });

  function somaPagamentos() {
    return estado.pagamentos.reduce((s, p) => s + p.valor, 0);
  }

  /* nomes legíveis das formas, lidos dos botões da própria tela */
  const NOMES_FORMA = {};
  $$('.forma-btn, .forma-pag').forEach((b) => {
    if (!NOMES_FORMA[b.dataset.forma]) NOMES_FORMA[b.dataset.forma] = b.textContent.trim();
  });

  function pintaPagamentos() {
    const corpo = $('#corpoPagamentos');
    if (!estado.pagamentos.length) {
      corpo.innerHTML = '<tr><td colspan="3" class="vazio">Nenhum pagamento informado.</td></tr>';
    } else {
      corpo.innerHTML = estado.pagamentos.map((p, i) => {
        const nome = NOMES_FORMA[p.forma] || p.forma;
        return '<tr><td>' + nome + (p.parcelas > 1 ? ' · ' + p.parcelas + 'x' : '') +
          '</td><td class="num">' + brl(p.valor) +
          '</td><td><button type="button" class="btn-x" data-remove-pag="' + i + '">×</button></td></tr>';
      }).join('');
    }
    const informado = somaPagamentos();
    const total = totalVenda();
    const restante = Math.max(0, total - informado);
    const troco = Math.max(0, informado - total);
    $('#pagTotal').textContent = brl(total);
    $('#pagInformado').textContent = brl(informado);
    $('#pagRestante').textContent = brl(restante);
    $('#pagTroco').textContent = brl(troco);
    if (restante <= 0.001) {
      $('#pagDica').textContent = troco > 0.001
        ? 'Pagamento completo. Troco a devolver: ' + brl(troco) + '.'
        : 'Pagamento completo. Pode confirmar a venda (F10).';
    } else {
      $('#pagDica').textContent = 'Faltam ' + brl(restante) + ' para completar a venda.';
    }
  }

  $('#corpoPagamentos').addEventListener('click', (e) => {
    const b = e.target.closest('[data-remove-pag]');
    if (!b) return;
    estado.pagamentos.splice(+b.dataset.removePag, 1);
    pintaPagamentos();
  });

  $('#btnAddPagamento').addEventListener('click', () => {
    if (!estado.itens.length) { FS.toast('Carrinho vazio.', 'erro'); return; }
    let v = num($('#pagValor').value);
    const restante = Math.max(0, totalVenda() - somaPagamentos());
    if (restante > 0 && (v <= 0)) v = restante;
    if (v <= 0) { FS.toast('Informe o valor recebido.', 'erro'); return; }
    const parcelas = parseInt($('#pagParcelas').value, 10) || 1;
    estado.pagamentos.push({ forma: estado.formaSelecionada, valor: v, parcelas });
    $('#pagValor').value = '';
    $('#pagParcelas').value = '1';
    pintaPagamentos();
    const proximoRestante = Math.max(0, totalVenda() - somaPagamentos());
    if (proximoRestante <= 0.001) $('#btnFinalizar').focus();
    else $('#pagValor').focus();
  });

  $('#btnLimparPagamentos').addEventListener('click', () => {
    estado.pagamentos = [];
    pintaPagamentos();
  });

  $('#btnPagamento').addEventListener('click', () => {
    if (!estado.itens.length) { FS.toast('Adicione itens antes de receber.', 'erro'); return; }
    estado.pagamentos = [];
    pintaFormas();
    pintaPagamentos();
    abrir('modalPagamento');
    setTimeout(() => $('.forma-pag.ativo') && $('.forma-pag.ativo').focus(), 100);
  });

  /* ---------------- finalizar ---------------- */
  let enviando = false;
  async function finalizar() {
    if (enviando) return;
    if (!estado.itens.length) { FS.toast('Carrinho vazio.', 'erro'); return; }
    let pags = estado.pagamentos.slice();
    const restante = Math.max(0, totalVenda() - somaPagamentos());
    if (!pags.length) {
      pags = [{ forma: estado.formaSelecionada === 'fiado' ? 'ficha' : estado.formaSelecionada,
                valor: totalVenda(), parcelas: 1 }];
    } else if (restante > 0.001) {
      FS.toast('Informe o pagamento completo. Faltam ' + brl(restante) + '.', 'erro');
      return;
    } else {
      /* ajusta o último pagamento para fechar o valor exato (evita troco quebrado) */
      const soma = somaPagamentos();
      const dif = totalVenda() - soma;
      if (Math.abs(dif) > 0.001 && pags.length) pags[pags.length - 1].valor += dif;
    }
    if (pags.some((p) => p.forma === 'ficha') && !estado.cliente) {
      FS.toast('Venda na ficha exige cliente selecionado.', 'erro');
      return;
    }

    enviando = true;
    const btn = $('#btnFinalizar');
    const rotulo = btn.innerHTML;
    btn.innerHTML = 'Processando...';
    btn.disabled = true;
    try {
      const r = await fetch('/pdv/venda', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          cliente_id: estado.cliente ? estado.cliente.id : null,
          itens: estado.itens.map((i) => ({
            produto_id: i.produto_id, quantidade: i.qtd,
            preco_unitario: i.preco, desconto: i.desconto || 0,
          })),
          desconto: estado.descontoTotal,
          pagamentos: pags.map((p) => ({ forma: p.forma, valor: p.valor, parcelas: p.parcelas })),
          observacao: $('#pagObservacao').value.trim(),
          terminal: pdv.dataset.terminal,
        }),
      });
      const j = await r.json();
      if (!r.ok) { FS.toast(j.erro || 'Erro ao registrar a venda.', 'erro'); return; }

      /* sucesso */
      fechar('modalPagamento');
      $('#sucessoNumero').textContent = 'Venda nº ' + j.numero;
      $('#sucessoTotal').textContent = brl(j.total);
      $('#sucessoTroco').textContent = brl(j.troco || 0);
      $('#sucessoFiado').textContent = brl(j.fiado || 0);
      $('#btnImprimirCupom').href = j.cupom;
      $('#btnAbrirVenda').href = j.detalhe;
      const ov = $('#overlaySucesso');
      ov.hidden = false;
      ov.classList.add('show');
      /* imprime automaticamente se configurado */
      if (localStorage.getItem('fs-pdv-auto-imprimir') === 'sim') {
        setTimeout(() => window.open(j.cupom, '_blank'), 300);
      }
      estado.itens = [];
      estado.descontoTotal = 0;
      estado.pagamentos = [];
      estado.cliente = null;
      $('#chipCliente').textContent = 'Consumidor';
      $('#clienteId').value = '';
      $('#pagObservacao').value = '';
      localStorage.removeItem(CHAVE);
      pintaCarrinho();
      pintaPagamentos();
      setTimeout(() => $('#btnNovaVenda').focus(), 120);
    } catch (e) {
      FS.toast('Falha de conexão ao registrar a venda.', 'erro');
    } finally {
      enviando = false;
      btn.innerHTML = rotulo;
      btn.disabled = false;
    }
  }

  $('#btnFinalizar').addEventListener('click', finalizar);

  function novaVenda() {
    const ov = $('#overlaySucesso');
    ov.classList.remove('show');
    ov.hidden = true;
    campoBusca.value = '';
    resultados.innerHTML = dica();
    campoBusca.focus();
  }
  $('#btnNovaVenda').addEventListener('click', novaVenda);

  /* ---------------- atalhos de teclado ---------------- */
  document.addEventListener('keydown', (e) => {
    const digitando = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName);
    const overlay = $('#overlaySucesso');
    const pagamentoAberto = !$('#modalPagamento').hidden;

    if (e.key === 'Enter' && overlay && !overlay.hidden) { e.preventDefault(); novaVenda(); return; }

    if (e.key === 'Escape') {
      /* fase de captura: fecha o modal e impede o handler global de limpar o carrinho */
      const aberto = $$('.modal:not([hidden])').pop();
      if (aberto) {
        e.preventDefault();
        e.stopPropagation();
        fecharModal(aberto.id);
        estado.descontoItemIndice = null;
        campoBusca.focus();
        return;
      }
      if (estado.itens.length) $('#btnLimpar').click();
      return;
    }

    switch (e.key) {
      case 'F2':
        e.preventDefault();
        campoBusca.focus();
        campoBusca.select();
        break;
      case 'F4':
        e.preventDefault();
        abrir('modalCliente');
        setTimeout(() => $('#buscaCliente').focus(), 80);
        break;
      case 'F7':
        e.preventDefault();
        $('#btnDescontoItem').click();
        break;
      case 'F8':
        e.preventDefault();
        $('#btnDescontoTotal').click();
        break;
      case 'F9':
        e.preventDefault();
        if (!pagamentoAberto) $('#btnPagamento').click();
        break;
      case 'F10':
        e.preventDefault();
        if (pagamentoAberto) finalizar();
        break;
      default:
        /* digitando no campo de busca, ENTER já é tratado ali */
        if (digitando) break;
        break;
    }
  }, true); /* captura: roda antes do handler global e fecha modais com ESC */

  /* impede que F-keys disparem comportamento do navegador */
  ['F2', 'F4', 'F7', 'F8', 'F9', 'F10'].forEach((k) => {
    window.addEventListener('keydown', (e) => { if (e.key === k) e.preventDefault(); });
  });

  /* ---------------- inicial ---------------- */
  pintaCarrinho();
  pintaFormas();
  campoBusca.focus();
})();
