# Lua MediaPaper

> Um projeto feito para minha amiga Lua! Feito com muito carinho...

[Baixar o executável portátil para Windows](https://github.com/KKannon/LUA-MediaPaper/releases/latest/download/Lua-MediaPaper.exe) · [Ver releases](https://github.com/KKannon/LUA-MediaPaper/releases)

Wallpapers de fotos, vídeos e GIFs por link, com relógio, tela cheia e ferramentas de documentos. Interface em português, React + TypeScript + Tailwind CSS e componentes **shadcn/ui**. Backend Django com Waitress, compartilhado entre o executável portátil e o servidor.

## Abrir no Windows

Baixe **Lua-MediaPaper.exe** na [última release](https://github.com/KKannon/LUA-MediaPaper/releases/latest) e execute. No projeto compilado, o arquivo fica em `dist/Lua-MediaPaper.exe`. Não precisa instalar Python, Node ou outro programa. O navegador abre em **http://127.0.0.1:8765/** e um ícone da Lua aparece na bandeja do Windows.

- Fechar o navegador mantém o aplicativo na bandeja.
- Clique duas vezes no ícone, ou use **Abrir Lua MediaPaper**, para voltar.
- Na primeira execução normal, o app ativa a inicialização com o Windows para o usuário atual, sem exigir administrador. Depois disso ele inicia silenciosamente na bandeja.
- Ative ou desative a opção em **Definições → Iniciar com o Windows**, ou no menu da bandeja.
- Para fechar o processo, use **Encerrar** no menu da bandeja.
- Mantenha o executável em uma pasta estável. Se mudar de lugar, abra-o novamente para atualizar o caminho de inicialização.
- Para abrir sem ativar a inicialização na primeira execução: `Lua-MediaPaper.exe --no-autostart`.
- Para iniciar apenas na bandeja: `Lua-MediaPaper.exe --background`.
- Para usar outra porta: `Lua-MediaPaper.exe --port 9000`.
- Para aceitar conexões apenas deste computador: `Lua-MediaPaper.exe --host 127.0.0.1`.
- Diagnósticos do executável ficam em `%LOCALAPPDATA%/LuaMediaPaper/lua.log`.

### Acesso pela rede

O executável fica disponível para outros dispositivos da mesma rede (celular, TV, outro PC) na porta **8765**. O endereço aparece no menu da bandeja (**Na rede: 192.168.x.x:8765**) e em **Definições → Aplicativo e sistema**. Por exemplo, abra `http://192.168.0.20:8765/live` em outro aparelho.

- Na primeira execução, o Firewall do Windows pode perguntar se o app pode se comunicar na rede: permita em **Redes privadas**.
- Os endereços IP e o nome deste computador são aceitos automaticamente; outros cabeçalhos `Host` são recusados. Se o IP mudar, reinicie o app pela bandeja.
- Qualquer pessoa na mesma rede pode ver e alterar o wallpaper, pois o app não tem login. Use apenas em redes de confiança ou inicie com `--host 127.0.0.1`.
- **Iniciar com o Windows** só pode ser alterado no próprio computador.

O wallpaper ocupa a janela do aplicativo ou toda a tela usando o modo tela cheia. Ele **não substitui o fundo nativo do Windows atrás dos ícones**. Use **Abrir /live** na Home, ou o ícone de maximizar da prévia para tela cheia imediata. Saia com **Esc**.

## /live: seu wallpaper ao vivo

Abra **http://127.0.0.1:8765/live** ou clique em **Abrir /live** na Home. No servidor, use `https://SEU-DOMINIO/live`. Essa rota preenche a janela somente com o wallpaper e o relógio/data que você escolher, sem navbar, badges de prévia, rótulo de fotografia, rodapé ou controles de configuração. A Home mantém a interface de edição.

Deixe `/live` aberto e altere o wallpaper ou as preferências em outra aba, navegador ou dispositivo conectado à mesma instância. As mudanças aparecem automaticamente, sem recarregar, em aproximadamente **um segundo**. Cada instância compartilha um wallpaper. O `/live` é um leitor e não sobrescreve o estado do servidor. A sincronização usa requisições condicionais com ETag; quando não há mudanças, não transfere a configuração novamente. Uma interrupção da rede mantém a última imagem e a sincronização é retomada automaticamente.

Pressione **F** ou dê **dois cliques** no `/live` para entrar/sair da tela cheia nativa do navegador. **Esc** sai da tela cheia. O navegador exige uma ação do usuário para ocultar suas barras; apenas visitar uma URL não pode forçar esse modo.

**Manter a tela ligada:** a opção **Definições → Manter tela ligada no /live** vem ativada. Usa a [Screen Wake Lock API](https://developer.mozilla.org/en-US/docs/Web/API/Screen_Wake_Lock_API), libera o bloqueio ao sair da página e tenta recuperá-lo quando a página volta a ficar visível. Requer navegador compatível e contexto seguro: **HTTPS** ou **localhost/127.0.0.1**. Acesso por HTTP a um IP da rede não oferece essa API. O sistema, a economia de bateria e as permissões do navegador podem revogar o bloqueio; nesses casos o app não consegue garantir que a tela fique ligada. Não altera permanentemente as configurações de energia do dispositivo.

Se o navegador bloquear um vídeo com som, o `/live` mostra somente um botão para iniciar a reprodução. Deixe **Silenciar vídeos** ativado para facilitar a reprodução automática.

## Rotas

| Rota | Conteúdo |
| --- | --- |
| `/` ou `/home` | Wallpaper, coleção, link de mídia e controles |
| `/live` | Wallpaper limpo em tela cheia, sincronizado com a edição |
| `/definicoes` | Relógio, data, enquadramento, brilho, vídeo e inicialização |
| `/mais` | Catálogo de ferramentas |
| `/mais/epub-pdf` | Conversor de EPUB para PDF |
| `/api/status` | Status, versão e recursos do modo de execução |
| `/api/wallpaper` | GET com ETag e PATCH parcial de mídia/preferências; alterações exigem CSRF |
| `/api/convert` | POST multipart: `file`, `pageSize` e `fontSize`; retorna PDF |
| `/api/startup` | POST JSON `{"enabled":true}`; somente no modo desktop e via loopback |

## Wallpapers

Cole uma URL HTTP/HTTPS **direta** de imagem, GIF, MP4, WebM ou outro formato reproduzível pelo navegador. O tipo pode ser detectado pela extensão ou escolhido manualmente, inclusive para links sem extensão. Links de páginas do Vimeo e de outros sites de vídeo não são arquivos de vídeo; o YouTube tem suporte próprio (veja abaixo). Formatos e codecs dependem do navegador. Alguns sites bloqueiam a incorporação; o app mostra um erro e permite voltar ao wallpaper inicial.

O wallpaper atual e as preferências ficam em SQLite no servidor e são compartilhados por todas as páginas daquela instância. O executável salva os dados em `%LOCALAPPDATA%/LuaMediaPaper/data`; o servidor Python usa `~/.lua-mediapaper`, configurável por `LUAMP_DATA_DIR`; o Compose mantém os dados no volume `lua-data`, inclusive após recriar o contêiner. A primeira página de edição importa as preferências locais antigas uma única vez, sem substituir um estado já configurado.

A coleção pessoal de links permanece no `localStorage` deste navegador e endereço, incluindo a porta, e contém os últimos 20 links. Os quatro wallpapers iniciais são arquivos locais incluídos no executável: funcionam sem internet. Mídias externas precisam de acesso à origem. Vídeos têm pausa, reprodução, som, repetição e reprodução automática; GIFs seguem a animação do arquivo. A reprodução automática com som pode ser bloqueada pelo navegador.

## Vídeos do YouTube

Cole o link de um vídeo do YouTube (`youtube.com/watch`, `youtu.be`, Shorts) de **até 20 minutos** e clique em **Baixar e aplicar YouTube**. O app baixa vídeo e áudio na **melhor resolução disponível, até 4K**, junta tudo em MP4 e aplica como wallpaper quando termina. Se houver 4K e 1080p, fica o 4K. Na mesma resolução, prefere VP9, que roda mais leve que AV1. A tela mostra o progresso, e o download pode ser cancelado.

- Só um vídeo baixado fica guardado. Ao trocar de wallpaper (outro vídeo do YouTube, foto ou link), o vídeo anterior é **apagado** automaticamente. Durante um novo download, o vídeo atual continua tocando até o novo ficar pronto.
- Lives, playlists e vídeos com mais de 20 minutos são recusados antes de baixar. O download é interrompido se o disco ficar com menos de 512 MB livres.
- A coleção guarda o link do YouTube: escolher o item de novo baixa o vídeo outra vez.
- O executável já inclui ffmpeg, ffprobe e Node.js; não precisa instalar nada. No modo servidor, eles precisam estar no PATH (o Docker já instala).
- Vídeos ficam em `media` dentro da pasta de dados. O YouTube às vezes pede verificação anti-robô para conexões de datacenter/VPN; em casa isso é raro.

## EPUB para PDF

Selecione ou arraste um EPUB de até **30 MB**. Escolha papel A4 ou Carta e tamanho de texto 10, 11, 12 ou 14 pt. O processamento preserva a ordem de leitura, títulos, parágrafos, negrito, itálico, listas e imagens raster internas. Cada capítulo começa em uma página nova e o PDF recebe numeração. Quando ficar pronto, clique em **Baixar PDF**.

O conversor usa um layout de leitura próprio: CSS do EPUB, fontes especiais, tabelas e layouts complexos não são reproduzidos fielmente. EPUBs com recursos criptografados são recusados, incluindo publicações com DRM ou fontes ofuscadas. Scripts não são executados e recursos remotos não são buscados. O limite descompactado é 150 MB, com até 4.000 entradas e até 20 MB por recurso. Arquivos são processados em memória ou em arquivos temporários gerenciados pelo Django; não são salvos em uma biblioteca permanente nem enviados a serviços externos.

## Desenvolvimento

Requisitos: Python 3.12+ (Django 6), Node.js 22+ e npm. Esta entrega foi compilada com Python 3.14 e Node 24, para Windows x64.

```powershell
python -m venv env
.\env\Scripts\python.exe -m pip install -r requirements-dev.txt
cd frontend
npm ci
npm run build
cd ..
.\env\Scripts\python.exe launcher.py --server
```

Para atualizar a interface durante o desenvolvimento, mantenha o backend acima e execute `npm run dev` na pasta `frontend`. Abra o endereço do Vite; as chamadas `/api` usam o proxy para a porta 8765. Os wallpapers também são encaminhados ao backend.

Para recompilar o executável:

```powershell
& .\scripts\build-portable.ps1
```

Saída: `dist/Lua-MediaPaper.exe`, um único arquivo. O script inclui frontend, imagens, fontes, servidor e integração da bandeja. Depois de compilar, faça o teste sem alterar a bandeja ou a inicialização:

```powershell
$test = Start-Process -FilePath .\dist\Lua-MediaPaper.exe -ArgumentList '--smoke-test' -WindowStyle Hidden -PassThru -Wait
$test.ExitCode
Get-Content lua-smoke-test.json
```

## Servidor próprio

No Windows ou Linux, instale `requirements.txt`, compile o frontend e execute:

```powershell
$env:LUAMP_ALLOWED_HOSTS = 'localhost,127.0.0.1,192.168.1.100,lua.seudominio.com'
$env:LUAMP_SECRET_KEY = 'defina-uma-chave-longa-e-aleatoria'
.\env\Scripts\python.exe launcher.py --server --port 8765
```

O servidor escuta em `0.0.0.0` por padrão e mostra os endereços da rede no terminal (`Na rede: http://...`). Abra `http://IP-DO-SERVIDOR:8765/`. Sem `LUAMP_ALLOWED_HOSTS`, os IPs e o nome da máquina são aceitos automaticamente; defina a variável para incluir um domínio. No Linux, use `export` para as variáveis e o Python do seu ambiente virtual. O modo servidor não cria ícone de bandeja nem altera a inicialização do Windows. O executável também aceita `--server`, mas a distribuição Python ou Docker permite acompanhar os logs no terminal.

Alternativamente, copie `.env.example` para `.env`, configure a chave e os hosts e execute:

```sh
docker compose up -d --build
```

O Compose reinicia o serviço automaticamente. Acesse `http://HOST:8765/` e as rotas da tabela acima. O app não inclui contas ou login; para acesso pela internet, configure HTTPS e autenticação no seu proxy reverso. Liste o domínio em `LUAMP_ALLOWED_HOSTS` e, quando necessário, a origem HTTPS em `LUAMP_CSRF_ORIGINS`. Configure limite de upload de pelo menos 35 MB no proxy. O acesso é pela raiz do domínio; prefixos como `/lua/` exigem configuração adicional. O Docker usa as versões fixadas em `requirements-lock.txt`.

## Verificação

```powershell
.\env\Scripts\python.exe manage.py check
.\env\Scripts\python.exe manage.py test --verbosity 2
cd frontend
npm test
npm run build
```

Os testes do backend e 11 testes do frontend passaram. Eles verificam PDF real, ordem dos capítulos, acentos, imagens, paginação de capítulos longos, A4/Carta, EPUB inválido/criptografado, limites de ZIP, ausência de downloads externos, CSRF, rotas e restrições da API de inicialização. Os testes adicionais cobrem sincronização entre páginas, recuperação de conexão, concorrência de escrita, importação inicial, ETag e ciclo de aquisição/liberação do bloqueio de tela. O executável Windows passou no smoke test independente e foi iniciado em modo bandeja, com resposta HTTP e registro de inicialização automática confirmados. Na interface foram testados vídeo remoto, GIF animado, tela cheia/Esc, persistência das preferências, conversão e download do PDF. O layout foi inspecionado em tela estreita e desktop. Docker foi preparado, mas não executado neste ambiente, onde o comando Docker não está instalado.

## Créditos

Componentes gerados pelo registro oficial do [shadcn/ui](https://ui.shadcn.com/), com Radix UI. Empacotamento com [PyInstaller](https://pyinstaller.org/). Wallpapers iniciais do Unsplash: [floresta](https://images.unsplash.com/photo-1448375240586-882707db888b), [montanha](https://images.unsplash.com/photo-1464822759023-fed622ff2c3b), [mar](https://images.unsplash.com/photo-1518837695005-2083093ee35b), [dunas](https://images.unsplash.com/photo-1509316785289-025f5b846b35). As fontes Bitstream Vera e sua licença acompanham o ReportLab.
