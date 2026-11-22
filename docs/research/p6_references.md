# P6 — источники (проверенные)

**Как проверялись источники.** Каждая запись на этапе P6 сверена с первоисточником:

* страницы аннотаций arXiv, страницы трудов NeurIPS/PMLR/JMLR или блог-трек ICLR;
* для статей, закрытых входом у издателя, — запись Semantic Scholar Graph API, сопоставленная по DOI.

«Проверено» относится к названию, авторам, году и месту публикации, как они указаны на этой странице. Если
утверждение о содержании в документах P6 выходит за рамки аннотации, это отмечено в записи. Один источник
проверить не удалось, и в документах P6 он **не цитируется**: Kapturowski et al., «Recurrent Experience
Replay in Distributed Reinforcement Learning» (R2D2) — его страницы отвечали ограничением частоты запросов
или проверкой на бота.

Библиографические описания (названия, авторы, места публикации) приводятся на языке оригинала.

## Обязательные источники проекта

| источник | значение |
|---|---|
| Genesis Hackathon, *FinTech case: RL environments for financial-audit model training* (PDF кейса, 2026) | исходные требования (§03–§10) |
| Genesis Hackathon, *Genesis FinTech: определения проверок* (`fintech-checks.txt`), опубликованы 2026-11-20 | **обязательные** контракты оценки: адаптер, блоки 1–4, соглашения matcher |
| Gymnasium Env API, https://gymnasium.farama.org/api/env/ | семантика reset/step, `terminated` и `truncated` |

## Обучение с подкреплением

| ключ | источник | проверенный URL | для чего используется |
|---|---|---|---|
| Kaelbling1998 | L. P. Kaelbling, M. L. Littman, A. R. Cassandra. Planning and Acting in Partially Observable Stochastic Domains. *Artificial Intelligence* 101:99–134, 1998. DOI 10.1016/S0004-3702(98)00023-X | запись Semantic Scholar | постановка POMDP |
| Sutton1999 | R. S. Sutton, D. Precup, S. Singh. Between MDPs and Semi-MDPs: A Framework for Temporal Abstraction in Reinforcement Learning. *Artificial Intelligence* 112:181–211, 1999. DOI 10.1016/S0004-3702(99)00052-1 | запись Semantic Scholar | опции, иерархические действия |
| Ng1999 | A. Y. Ng, D. Harada, S. Russell. Policy Invariance Under Reward Transformations: Theory and Application to Reward Shaping. ICML 1999 | запись Semantic Scholar (только библиография) | потенциальное формирование награды (аннотация на P6 не перечитывалась; утверждение — известный результат статьи) |
| Bengio2009 | Y. Bengio, J. Louradour, R. Collobert, J. Weston. Curriculum Learning. ICML 2009. DOI 10.1145/1553374.1553380 | запись Semantic Scholar (только библиография) | понятие учебной программы |
| Mnih2015 | V. Mnih et al. Human-level control through deep reinforcement learning. *Nature* 518:529–533, 2015. DOI 10.1038/nature14236 | запись Semantic Scholar | DQN |
| Schulman2015 | J. Schulman, P. Moritz, S. Levine, M. Jordan, P. Abbeel. High-Dimensional Continuous Control Using Generalized Advantage Estimation. arXiv:1506.02438 (ICLR 2016 по ссылке DBLP) | https://arxiv.org/abs/1506.02438 | GAE |
| Schulman2017 | J. Schulman et al. Proximal Policy Optimization Algorithms. arXiv:1707.06347, 2017 | https://arxiv.org/abs/1707.06347 | PPO |
| Dabney2017 | W. Dabney, M. Rowland, M. G. Bellemare, R. Munos. Distributional Reinforcement Learning with Quantile Regression. arXiv:1710.10044, 2017 | https://arxiv.org/abs/1710.10044 | QR-DQN |
| Hausknecht2015a | M. Hausknecht, P. Stone. Deep Recurrent Q-Learning for Partially Observable MDPs. arXiv:1507.06527, 2015 | https://arxiv.org/abs/1507.06527 | рекуррентность при частичной наблюдаемости |
| Hausknecht2015b | M. Hausknecht, P. Stone. Deep Reinforcement Learning in Parameterized Action Space. arXiv:1511.04143 (ICLR 2016 по ссылке DBLP) | https://arxiv.org/abs/1511.04143 | параметризованные действия |
| Xiong2018 | J. Xiong et al. Parametrized Deep Q-Networks Learning: Reinforcement Learning with Discrete-Continuous Hybrid Action Space. arXiv:1810.06394, 2018 | https://arxiv.org/abs/1810.06394 | P-DQN |
| Bester2019 | C. J. Bester, S. D. James, G. D. Konidaris. Multi-Pass Q-Networks for Deep Reinforcement Learning with Parameterised Action Spaces. arXiv:1905.04388, 2019 | https://arxiv.org/abs/1905.04388 | MP-DQN |
| He2016 | J. He et al. Deep Reinforcement Learning with a Natural Language Action Space. arXiv:1511.04636 (принята на ACL 2016) | https://arxiv.org/abs/1511.04636 | DRRN: оценка переменного множества действий-кандидатов |
| Huang2020 | S. Huang, S. Ontañón. A Closer Look at Invalid Action Masking in Policy Gradient Algorithms. arXiv:2006.14171 (FLAIRS 35, 2022) | https://arxiv.org/abs/2006.14171 | маскирование действий |
| Vinyals2019 | O. Vinyals et al. Grandmaster level in StarCraft II using multi-agent reinforcement learning. *Nature* 575:350–354, 2019. DOI 10.1038/s41586-019-1724-z | запись Semantic Scholar (только библиография) | пример структурированных действий в большом масштабе (архитектурных утверждений не делается) |
| Henderson2018 | P. Henderson et al. Deep Reinforcement Learning that Matters. arXiv:1709.06560 (AAAI 2018) | https://arxiv.org/abs/1709.06560 | воспроизводимость и отчётность |
| Agarwal2021 | R. Agarwal, M. Schwarzer, P. S. Castro, A. Courville, M. G. Bellemare. Deep Reinforcement Learning at the Edge of the Statistical Precipice. arXiv:2108.13264 (NeurIPS 2021) | https://arxiv.org/abs/2108.13264 | IQM, интервальные оценки, профили качества |
| Andrychowicz2020 | M. Andrychowicz et al. What Matters In On-Policy Reinforcement Learning? A Large-Scale Empirical Study. arXiv:2006.05990 | https://arxiv.org/abs/2006.05990 | выбор параметров PPO |
| Engstrom2020 | L. Engstrom et al. Implementation Matters in Deep Policy Gradients: A Case Study on PPO and TRPO. arXiv:2005.12729 (ICLR 2020) | https://arxiv.org/abs/2005.12729 | чувствительность к реализации |
| Huang2022 | S. Huang, R. F. J. Dossa, A. Raffin, A. Kanervisto, W. Wang. The 37 Implementation Details of Proximal Policy Optimization. ICLR Blog Track, 2022 | https://iclr-blog-track.github.io/2022/03/25/ppo-implementation-details/ | детали PPO, включая MultiDiscrete и LSTM |

## Подражание, офлайн-обучение, модели последовательностей

| ключ | источник | проверенный URL | для чего используется |
|---|---|---|---|
| Pomerleau1988 | D. A. Pomerleau. ALVINN: An Autonomous Land Vehicle in a Neural Network. NIPS 1988 | https://papers.nips.cc/paper_files/paper/1988/hash/812b4ba287f5ee0bc9d43bbf5bbe87fb-Abstract.html | клонирование поведения |
| Ross2010 | S. Ross, D. Bagnell. Efficient Reductions for Imitation Learning. AISTATS 2010, PMLR 9:661–668 | https://proceedings.mlr.press/v9/ross10a.html | накопление ошибок (квадратично по горизонту) |
| Ross2011 | S. Ross, G. J. Gordon, J. A. Bagnell. A Reduction of Imitation Learning and Structured Prediction to No-Regret Online Learning. arXiv:1011.0686 (AISTATS 2011) | https://arxiv.org/abs/1011.0686 | DAgger |
| Chen2019 | D. Chen, B. Zhou, V. Koltun, P. Krähenbühl. Learning by Cheating. arXiv:1912.12294 (CoRL 2019) | https://arxiv.org/abs/1912.12294 | привилегированный учитель → ученик |
| Warrington2021 | A. Warrington, J. W. Lavington, A. Ścibior, M. Schmidt, F. Wood. Robust Asymmetric Learning in POMDPs. arXiv:2012.15566 (ICML 2021) | https://arxiv.org/abs/2012.15566 | асимметричное подражание (эксперт не знает, чего не видит ученик) |
| Weihs2021 | L. Weihs et al. Bridging the Imitation Gap by Adaptive Insubordination. arXiv:2007.12173 (NeurIPS 2021) | https://arxiv.org/abs/2007.12173 | термин «imitation gap»; ADVISOR |
| Kumar2020 | A. Kumar, A. Zhou, G. Tucker, S. Levine. Conservative Q-Learning for Offline Reinforcement Learning. arXiv:2006.04779 | https://arxiv.org/abs/2006.04779 | CQL |
| Kostrikov2021 | I. Kostrikov, A. Nair, S. Levine. Offline Reinforcement Learning with Implicit Q-Learning. arXiv:2110.06169 | https://arxiv.org/abs/2110.06169 | IQL |
| Fu2020 | J. Fu, A. Kumar, O. Nachum, G. Tucker, S. Levine. D4RL: Datasets for Deep Data-Driven Reinforcement Learning. arXiv:2004.07219 | https://arxiv.org/abs/2004.07219 | офлайн-наборы данных |
| Fu2021 | J. Fu et al. Benchmarks for Deep Off-Policy Evaluation. arXiv:2103.16596 (ICLR 2021) | https://arxiv.org/abs/2103.16596 | OPE |
| Chen2021 | L. Chen et al. Decision Transformer: Reinforcement Learning via Sequence Modeling. arXiv:2106.01345 | https://arxiv.org/abs/2106.01345 | DT |
| Paster2022 | K. Paster, S. McIlraith, J. Ba. You Can't Count on Luck: Why Decision Transformers and RvS Fail in Stochastic Environments. arXiv:2205.15967 | https://arxiv.org/abs/2205.15967 | ограничения DT |

## Агенты, архитектуры, калибровка

| ключ | источник | проверенный URL | для чего используется |
|---|---|---|---|
| Yao2022a | S. Yao et al. ReAct: Synergizing Reasoning and Acting in Language Models. arXiv:2210.03629 (ICLR) | https://arxiv.org/abs/2210.03629 | LLM-агенты с инструментами |
| Schick2023 | T. Schick et al. Toolformer: Language Models Can Teach Themselves to Use Tools. arXiv:2302.04761 | https://arxiv.org/abs/2302.04761 | выбор инструментов и аргументов |
| Yao2022b | S. Yao, H. Chen, J. Yang, K. Narasimhan. WebShop: Towards Scalable Real-World Web Interaction with Grounded Language Agents. arXiv:2207.01206 (NeurIPS) | https://arxiv.org/abs/2207.01206 | похожая среда с инструментами (успех агента 29 % против 59 % у людей) |
| Cote2018 | M.-A. Côté et al. TextWorld: A Learning Environment for Text-based Games. arXiv:1806.11532 | https://arxiv.org/abs/1806.11532 | среды с комбинаторными структурированными действиями |
| Garcez2020 | A. d'Avila Garcez, L. C. Lamb. Neurosymbolic AI: The 3rd Wave. arXiv:2012.05876 | https://arxiv.org/abs/2012.05876 | понятие нейросимвольного подхода |
| Vinyals2015 | O. Vinyals, M. Fortunato, N. Jaitly. Pointer Networks. arXiv:1506.03134 | https://arxiv.org/abs/1506.03134 | выбор идентификаторов из переменного входного множества |
| Zaheer2017 | M. Zaheer et al. Deep Sets. arXiv:1703.06114 (NIPS 2017) | https://arxiv.org/abs/1703.06114 | кодировщики, инвариантные к перестановкам |
| Guo2017 | C. Guo, G. Pleiss, Y. Sun, K. Q. Weinberger. On Calibration of Modern Neural Networks. arXiv:1706.04599 (ICML 2017) | https://arxiv.org/abs/1706.04599 | ECE, температурное масштабирование |

## Фреймворки (статьи и официальная документация)

| ключ | источник / страница | использованные проверенные факты |
|---|---|---|
| Paszke2019 | A. Paszke et al. PyTorch: An Imperative Style, High-Performance Deep Learning Library. arXiv:1912.01703 (NeurIPS 2019); https://pytorch.org/get-started/locally/ ; https://pypi.org/project/torch/ | поддерживаются Windows и Linux; `torch` 2.15.0 требует Python ≥ 3.11 |
| Towers2024 | M. Towers et al. Gymnasium: A Standard Interface for Reinforcement Learning Environments. arXiv:2407.17032; https://gymnasium.farama.org/api/spaces/ ; https://pypi.org/project/gymnasium/ | пространства Box, Discrete, MultiBinary, MultiDiscrete, Text, Dict, Tuple, Sequence, Graph, OneOf; 1.4.0, Python ≥ 3.10, MIT |
| Raffin2021 | A. Raffin et al. Stable-Baselines3: Reliable Reinforcement Learning Implementations. JMLR 22(268):1–8, 2021; https://stable-baselines3.readthedocs.io/en/master/guide/algos.html ; …/guide/install.html ; https://pypi.org/project/stable-baselines3/ | действия PPO Box/Discrete/MultiDiscrete/MultiBinary; DQN только Discrete; наблюдения Dict одного уровня; требует Python 3.10+ и PyTorch ≥ 2.8; 2.9.2 |
| sb3-contrib | https://sb3-contrib.readthedocs.io/en/master/ (страницы MaskablePPO, RecurrentPPO) | «Experimental code»; MaskablePPO маскирует Discrete/MultiDiscrete/MultiBinary, без рекуррентных политик; RecurrentPPO: MlpLstmPolicy/CnnLstmPolicy/MultiInputLstmPolicy, без действий Dict; есть QR-DQN |
| Liang2018 | E. Liang et al. RLlib: Abstractions for Distributed Reinforcement Learning. arXiv:1712.09381 (ICML 2018); https://docs.ray.io/en/latest/ray-overview/installation.html | «Ray on Windows is currently in beta» |
| Huang2021 | S. Huang, R. F. J. Dossa, C. Ye, J. Braga. CleanRL: High-quality Single-file Implementations of Deep Reinforcement Learning Algorithms. arXiv:2111.08819; https://github.com/vwxyzjn/cleanrl | «not a modular library … not meant to be imported»; MIT; README указывает Python < 3.11 |
| Wolf2019 | T. Wolf et al. HuggingFace's Transformers: State-of-the-art Natural Language Processing. arXiv:1910.03771; https://huggingface.co/docs/transformers/model_doc/decision_transformer | `DecisionTransformerModel` для векторных состояний |
