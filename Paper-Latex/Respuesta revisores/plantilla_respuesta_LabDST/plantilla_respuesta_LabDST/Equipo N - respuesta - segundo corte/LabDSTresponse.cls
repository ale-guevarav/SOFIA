%% =============================================================================
%% LabDSTresponse.cls -- Respuesta a los revisores, papers LabDST RoboCoffee (ITESO)
%%
%% Documento APARTE del paper del equipo (como LabDSTreview.cls, pero escrito por
%% el equipo). Vive en la carpeta hermana "Equipo N - respuesta - segundo corte"
%% y lee las etiquetas del paper REVISADO (\linelabel{ln:...}, \label{sec:...},
%% \label{fig:...}, \label{tab:...}, \label{eq:...}) desde su .aux con xr. Asi,
%% "line 42" o "Section III" en la respuesta siempre coinciden con el PDF del paper.
%%
%% Uso:
%%   \documentclass{LabDSTresponse}
%%   \LabDSTpaper{"../Equipo 0 - segundo corte/Equipo 0 - segundo corte"}
%%                                          % en el preambulo; ruta SIN extension,
%%                                          % entre comillas si tiene espacios
%%   \LabDSTtitle{Second Cut}{Team 0}{Titulo del paper}
%%
%%   \LabDSTsection{Titulo}             bloque libre (agradecimiento, resumen...)
%%   \LabDSTsummary                     matriz observacion-respuesta-cambio
%%                                      (se llena sola; compilar dos veces)
%%   \LabDSTreviewer{n}{Enfoque}        inicia "Reviewer n"
%%   \LabDSTcomment{Clave}{Estado}{Ubicacion}{Comentario}{Respuesta}
%%        Clave      la del PDF de observaciones: R1.3, R2.1, ...
%%        Estado     A = Addressed, P = Partially addressed,
%%                   N = Not addressed (justified)
%%        Ubicacion  donde esta el cambio en el paper revisado, con \rln, \ref...
%%        Comentario copia TEXTUAL de la observacion del revisor
%%        Respuesta  que se hizo, donde, y por que (o por que no)
%%   \LabDSTquote{texto}                cita del texto NUEVO del paper
%%
%%   \rln{x}  -> "line NN"     \rlns{x}{y} -> "lines NN--MM"   (etiqueta ln:x)
%%   \Rln{x}  -> "Line NN"     \Rlns{x}{y} -> "Lines NN--MM"   (inicio de oracion)
%%   \ref{sec:...}, \ref{fig:...}, \ref{tab:...}, \eqref{eq:...} funcionan igual
%%
%% Compilacion: primero el paper (pdflatex, bibtex, pdflatex, pdflatex), despues
%% este documento DOS veces. Si el paper cambia, se recompila la respuesta.
%% "??" en el PDF = etiqueta mal escrita, paper sin compilar o ruta incorrecta.
%% =============================================================================
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{LabDSTresponse}[2026/10/01 LabDST response to reviewers]

\DeclareOption*{\PassOptionsToClass{\CurrentOption}{article}}
\ProcessOptions\relax
\LoadClass[10pt,letterpaper]{article}

\RequirePackage[T1]{fontenc}
\RequirePackage{mathptmx}
\RequirePackage[scaled=0.92]{helvet}
\renewcommand\ttdefault{lmtt}   % tipografia vectorial para \texttt (evita Type 3)
\RequirePackage[margin=0.75in]{geometry}
\RequirePackage{amsmath}
\RequirePackage{array}
\RequirePackage{longtable}
\RequirePackage{xcolor}
\RequirePackage{xr}

\setlength\parindent{0pt}
\setlength\parskip{3pt plus 1pt}
\sloppy
\pagestyle{plain}

%% --- Vinculo con el paper revisado --------------------------------------------
\newcommand\LabDSTpaper[1]{\externaldocument{#1}}

% lineno guarda en el .aux del paper \newlabel{ln:x}{{\getpagewiselinenumber{N}}{pag}},
% donde N es el contador ANTES de la linea marcada: la linea impresa es N+1
% (es lo que hace \lineref de lineno). Aqui se reproduce sin cargar lineno.
\def\getpagewiselinenumber#1{\number\numexpr#1+1\relax}
\newcommand\rln[1]{line~\ref{ln:#1}}
\newcommand\rlns[2]{lines~\ref{ln:#1}--\ref{ln:#2}}
\newcommand\Rln[1]{Line~\ref{ln:#1}}
\newcommand\Rlns[2]{Lines~\ref{ln:#1}--\ref{ln:#2}}

%% --- Encabezado ---------------------------------------------------------------
\newcommand\LabDSTtitle[3]{%
  \begin{center}
  {\LARGE\bfseries Response to Reviewers --- #1}\par\medskip
  #2\quad$\cdot$\quad\textit{#3}
  \end{center}\medskip}

\newcommand\LabDSTsection[1]{%
  \par\bigskip{\large\bfseries #1}\par\nobreak\vspace{2pt}\hrule\nobreak\medskip}
\newcommand\LabDSTreviewer[2]{%
  \LabDSTsection{Reviewer #1\hfill{\normalsize\itshape #2}}}

%% --- Estado de cada respuesta -------------------------------------------------
\definecolor{LabDST@A}{rgb}{0.10,0.45,0.20}
\definecolor{LabDST@P}{rgb}{0.75,0.45,0.00}
\definecolor{LabDST@N}{rgb}{0.70,0.10,0.10}
\def\LabDST@name@A{Addressed}
\def\LabDST@name@P{Partially addressed}
\def\LabDST@name@N{Not addressed (justified)}
\newcommand\LabDST@status[1]{%
  \@ifundefined{LabDST@name@#1}%
    {\ClassError{LabDSTresponse}{Estado desconocido `#1'}{Use A, P o N.}}%
    {\textcolor{LabDST@#1}{\textbf{[\csname LabDST@name@#1\endcsname]}}}}

%% --- Comentario + respuesta ---------------------------------------------------
\newcommand\LabDSTcomment[5]{%
  \par\medskip
  \immediate\write\@auxout{\noexpand\LabDST@savedrow
    {\unexpanded{#1}}{\unexpanded{#2}}{\unexpanded{#3}}}%
  \noindent\textbf{#1}\enspace\LabDST@status{#2}\par\nobreak
  \begin{list}{}{\setlength\leftmargin{1.4em}\setlength\itemsep{2pt}%
    \setlength\parsep{2pt}\setlength\topsep{1pt}}
  \item[] {\color{black!70}\textit{Reviewer comment:} #4}
  \item[] \textbf{Response:} #5
  \item[] \textit{Changes in the revised paper:} #3
  \end{list}}

\newcommand\LabDSTquote[1]{%
  \par\smallskip
  {\leftskip=1.5em\rightskip=1.5em\small\textit{``#1''}\par}\smallskip}

%% --- Matriz observacion-respuesta-cambio (se arma desde el .aux) --------------
%% Cada \LabDSTcomment escribe su fila en el .aux; en la siguiente compilacion
%% \LabDSTsummary la imprime (por eso se compila dos veces). Columnas de ancho
%% fijo para que longtable no pida una tercera compilacion.
\newtoks\LabDST@rows
\newcounter{LabDST@total}\newcounter{LabDST@cA}\newcounter{LabDST@cP}\newcounter{LabDST@cN}
\newcommand\LabDST@savedrow[3]{%
  \global\LabDST@rows\expandafter{\the\LabDST@rows
    #1 & \LabDST@status{#2} & #3 \\ \hline}%
  \stepcounter{LabDST@total}%
  \@ifundefined{c@LabDST@c#2}{}{\stepcounter{LabDST@c#2}}}
\newcommand\LabDSTsummary{%
  \LabDSTsection{Summary of changes (observation--response--change matrix)}
  \ifnum\value{LabDST@total}=0
    \textit{(Compile this document twice to build the summary.)}\par
  \else
    \arabic{LabDST@total} observations:
    \arabic{LabDST@cA} addressed, \arabic{LabDST@cP} partially addressed,
    \arabic{LabDST@cN} not addressed (justified).\par\smallskip
    {\renewcommand\arraystretch{1.2}%
    \begin{longtable}{@{}p{1.1cm} p{3.9cm} >{\raggedright\arraybackslash}p{\dimexpr\linewidth-5cm-4\tabcolsep\relax}@{}}
    \hline
    \textbf{Key} & \textbf{Status} & \textbf{Location in the revised paper}\\
    \hline\endhead
    \the\LabDST@rows
    \end{longtable}}
  \fi}

\endinput
