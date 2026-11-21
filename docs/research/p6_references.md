# P6 — References (verified)

**How these were verified.** Every entry was checked during P6 against its primary page:
* arXiv abstract pages, NeurIPS/PMLR/JMLR proceedings pages, or the ICLR blog track;
* for papers behind publisher log-ins, the Semantic Scholar Graph API record, matched by DOI.

"Verified" covers title, authors, year and venue as shown on that page. Where a content claim in the P6
documents goes beyond the abstract, the entry says so. One item could not be verified and is **not
cited** in the P6 documents: Kapturowski et al., "Recurrent Experience Replay in Distributed
Reinforcement Learning" (R2D2), whose pages returned rate limits or bot challenges.

## Binding project sources

| source | relevance |
|---|---|
| Genesis Hackathon, *FinTech case: RL environments for financial-audit model training* (case PDF, 2026) | original requirements (§03–§10) |
| Genesis Hackathon, *Genesis FinTech: check definitions* (`fintech-checks.txt`), published 2026-11-20 | **binding** evaluation contracts: adapter, Blocks 1–4, matcher conventions |
| Gymnasium Env API, https://gymnasium.farama.org/api/env/ | reset/step semantics, `terminated` vs `truncated` |

## Reinforcement learning

| key | reference | verified URL | used for |
|---|---|---|---|
| Kaelbling1998 | L. P. Kaelbling, M. L. Littman, A. R. Cassandra. Planning and Acting in Partially Observable Stochastic Domains. *Artificial Intelligence* 101:99–134, 1998. DOI 10.1016/S0004-3702(98)00023-X | Semantic Scholar record | POMDP formulation |
| Sutton1999 | R. S. Sutton, D. Precup, S. Singh. Between MDPs and Semi-MDPs: A Framework for Temporal Abstraction in Reinforcement Learning. *Artificial Intelligence* 112:181–211, 1999. DOI 10.1016/S0004-3702(99)00052-1 | Semantic Scholar record | options / hierarchical actions |
| Ng1999 | A. Y. Ng, D. Harada, S. Russell. Policy Invariance Under Reward Transformations: Theory and Application to Reward Shaping. ICML 1999 | Semantic Scholar record (bibliographic only) | potential-based shaping (abstract not re-read in P6; claim from the paper's established result) |
| Bengio2009 | Y. Bengio, J. Louradour, R. Collobert, J. Weston. Curriculum Learning. ICML 2009. DOI 10.1145/1553374.1553380 | Semantic Scholar record (bibliographic only) | curriculum framing |
| Mnih2015 | V. Mnih et al. Human-level control through deep reinforcement learning. *Nature* 518:529–533, 2015. DOI 10.1038/nature14236 | Semantic Scholar record | DQN |
| Schulman2015 | J. Schulman, P. Moritz, S. Levine, M. Jordan, P. Abbeel. High-Dimensional Continuous Control Using Generalized Advantage Estimation. arXiv:1506.02438 (ICLR 2016 per DBLP link) | https://arxiv.org/abs/1506.02438 | GAE |
| Schulman2017 | J. Schulman et al. Proximal Policy Optimization Algorithms. arXiv:1707.06347, 2017 | https://arxiv.org/abs/1707.06347 | PPO |
| Dabney2017 | W. Dabney, M. Rowland, M. G. Bellemare, R. Munos. Distributional Reinforcement Learning with Quantile Regression. arXiv:1710.10044, 2017 | https://arxiv.org/abs/1710.10044 | QR-DQN |
| Hausknecht2015a | M. Hausknecht, P. Stone. Deep Recurrent Q-Learning for Partially Observable MDPs. arXiv:1507.06527, 2015 | https://arxiv.org/abs/1507.06527 | recurrence under partial observability |
| Hausknecht2015b | M. Hausknecht, P. Stone. Deep Reinforcement Learning in Parameterized Action Space. arXiv:1511.04143 (ICLR 2016 per DBLP link) | https://arxiv.org/abs/1511.04143 | parameterised actions |
| Xiong2018 | J. Xiong et al. Parametrized Deep Q-Networks Learning: Reinforcement Learning with Discrete-Continuous Hybrid Action Space. arXiv:1810.06394, 2018 | https://arxiv.org/abs/1810.06394 | P-DQN |
| Bester2019 | C. J. Bester, S. D. James, G. D. Konidaris. Multi-Pass Q-Networks for Deep Reinforcement Learning with Parameterised Action Spaces. arXiv:1905.04388, 2019 | https://arxiv.org/abs/1905.04388 | MP-DQN |
| He2016 | J. He et al. Deep Reinforcement Learning with a Natural Language Action Space. arXiv:1511.04636 (accepted by ACL 2016) | https://arxiv.org/abs/1511.04636 | DRRN: scoring variable candidate actions |
| Huang2020 | S. Huang, S. Ontañón. A Closer Look at Invalid Action Masking in Policy Gradient Algorithms. arXiv:2006.14171 (FLAIRS 35, 2022) | https://arxiv.org/abs/2006.14171 | action masking |
| Vinyals2019 | O. Vinyals et al. Grandmaster level in StarCraft II using multi-agent reinforcement learning. *Nature* 575:350–354, 2019. DOI 10.1038/s41586-019-1724-z | Semantic Scholar record (bibliographic only) | example of structured actions at scale (no architectural claim made) |
| Henderson2018 | P. Henderson et al. Deep Reinforcement Learning that Matters. arXiv:1709.06560 (AAAI 2018) | https://arxiv.org/abs/1709.06560 | reproducibility and reporting |
| Agarwal2021 | R. Agarwal, M. Schwarzer, P. S. Castro, A. Courville, M. G. Bellemare. Deep Reinforcement Learning at the Edge of the Statistical Precipice. arXiv:2108.13264 (NeurIPS 2021) | https://arxiv.org/abs/2108.13264 | IQM, interval estimates, performance profiles |
| Andrychowicz2020 | M. Andrychowicz et al. What Matters In On-Policy Reinforcement Learning? A Large-Scale Empirical Study. arXiv:2006.05990 | https://arxiv.org/abs/2006.05990 | PPO design choices |
| Engstrom2020 | L. Engstrom et al. Implementation Matters in Deep Policy Gradients: A Case Study on PPO and TRPO. arXiv:2005.12729 (ICLR 2020) | https://arxiv.org/abs/2005.12729 | implementation sensitivity |
| Huang2022 | S. Huang, R. F. J. Dossa, A. Raffin, A. Kanervisto, W. Wang. The 37 Implementation Details of Proximal Policy Optimization. ICLR Blog Track, 2022 | https://iclr-blog-track.github.io/2022/03/25/ppo-implementation-details/ | PPO details incl. MultiDiscrete and LSTM |

## Imitation, offline learning, sequence models

| key | reference | verified URL | used for |
|---|---|---|---|
| Pomerleau1988 | D. A. Pomerleau. ALVINN: An Autonomous Land Vehicle in a Neural Network. NIPS 1988 | https://papers.nips.cc/paper_files/paper/1988/hash/812b4ba287f5ee0bc9d43bbf5bbe87fb-Abstract.html | behaviour cloning |
| Ross2010 | S. Ross, D. Bagnell. Efficient Reductions for Imitation Learning. AISTATS 2010, PMLR 9:661–668 | https://proceedings.mlr.press/v9/ross10a.html | compounding errors (quadratic in horizon) |
| Ross2011 | S. Ross, G. J. Gordon, J. A. Bagnell. A Reduction of Imitation Learning and Structured Prediction to No-Regret Online Learning. arXiv:1011.0686 (AISTATS 2011) | https://arxiv.org/abs/1011.0686 | DAgger |
| Chen2019 | D. Chen, B. Zhou, V. Koltun, P. Krähenbühl. Learning by Cheating. arXiv:1912.12294 (CoRL 2019) | https://arxiv.org/abs/1912.12294 | privileged teacher → student |
| Warrington2021 | A. Warrington, J. W. Lavington, A. Ścibior, M. Schmidt, F. Wood. Robust Asymmetric Learning in POMDPs. arXiv:2012.15566 (ICML 2021) | https://arxiv.org/abs/2012.15566 | asymmetric imitation (expert unaware of what the trainee cannot see) |
| Weihs2021 | L. Weihs et al. Bridging the Imitation Gap by Adaptive Insubordination. arXiv:2007.12173 (NeurIPS 2021) | https://arxiv.org/abs/2007.12173 | the term "imitation gap"; ADVISOR |
| Kumar2020 | A. Kumar, A. Zhou, G. Tucker, S. Levine. Conservative Q-Learning for Offline Reinforcement Learning. arXiv:2006.04779 | https://arxiv.org/abs/2006.04779 | CQL |
| Kostrikov2021 | I. Kostrikov, A. Nair, S. Levine. Offline Reinforcement Learning with Implicit Q-Learning. arXiv:2110.06169 | https://arxiv.org/abs/2110.06169 | IQL |
| Fu2020 | J. Fu, A. Kumar, O. Nachum, G. Tucker, S. Levine. D4RL: Datasets for Deep Data-Driven Reinforcement Learning. arXiv:2004.07219 | https://arxiv.org/abs/2004.07219 | offline datasets |
| Fu2021 | J. Fu et al. Benchmarks for Deep Off-Policy Evaluation. arXiv:2103.16596 (ICLR 2021) | https://arxiv.org/abs/2103.16596 | OPE |
| Chen2021 | L. Chen et al. Decision Transformer: Reinforcement Learning via Sequence Modeling. arXiv:2106.01345 | https://arxiv.org/abs/2106.01345 | DT |
| Paster2022 | K. Paster, S. McIlraith, J. Ba. You Can't Count on Luck: Why Decision Transformers and RvS Fail in Stochastic Environments. arXiv:2205.15967 | https://arxiv.org/abs/2205.15967 | DT limitations |

## Agents, architectures, calibration

| key | reference | verified URL | used for |
|---|---|---|---|
| Yao2022a | S. Yao et al. ReAct: Synergizing Reasoning and Acting in Language Models. arXiv:2210.03629 (ICLR) | https://arxiv.org/abs/2210.03629 | LLM tool agents |
| Schick2023 | T. Schick et al. Toolformer: Language Models Can Teach Themselves to Use Tools. arXiv:2302.04761 | https://arxiv.org/abs/2302.04761 | tool selection and arguments |
| Yao2022b | S. Yao, H. Chen, J. Yang, K. Narasimhan. WebShop: Towards Scalable Real-World Web Interaction with Grounded Language Agents. arXiv:2207.01206 (NeurIPS) | https://arxiv.org/abs/2207.01206 | analogous tool environment (29 % agent vs 59 % human success) |
| Cote2018 | M.-A. Côté et al. TextWorld: A Learning Environment for Text-based Games. arXiv:1806.11532 | https://arxiv.org/abs/1806.11532 | combinatorial structured action environments |
| Garcez2020 | A. d'Avila Garcez, L. C. Lamb. Neurosymbolic AI: The 3rd Wave. arXiv:2012.05876 | https://arxiv.org/abs/2012.05876 | neuro-symbolic framing |
| Vinyals2015 | O. Vinyals, M. Fortunato, N. Jaitly. Pointer Networks. arXiv:1506.03134 | https://arxiv.org/abs/1506.03134 | selecting ids from a variable input set |
| Zaheer2017 | M. Zaheer et al. Deep Sets. arXiv:1703.06114 (NIPS 2017) | https://arxiv.org/abs/1703.06114 | permutation-invariant encoders |
| Guo2017 | C. Guo, G. Pleiss, Y. Sun, K. Q. Weinberger. On Calibration of Modern Neural Networks. arXiv:1706.04599 (ICML 2017) | https://arxiv.org/abs/1706.04599 | ECE, temperature scaling |

## Frameworks (papers and official documentation)

| key | reference / page | verified facts used |
|---|---|---|
| Paszke2019 | A. Paszke et al. PyTorch: An Imperative Style, High-Performance Deep Learning Library. arXiv:1912.01703 (NeurIPS 2019); https://pytorch.org/get-started/locally/ ; https://pypi.org/project/torch/ | Windows and Linux supported; `torch` 2.15.0 requires Python ≥ 3.11 |
| Towers2024 | M. Towers et al. Gymnasium: A Standard Interface for Reinforcement Learning Environments. arXiv:2407.17032; https://gymnasium.farama.org/api/spaces/ ; https://pypi.org/project/gymnasium/ | spaces Box, Discrete, MultiBinary, MultiDiscrete, Text, Dict, Tuple, Sequence, Graph, OneOf; 1.4.0, Python ≥ 3.10, MIT |
| Raffin2021 | A. Raffin et al. Stable-Baselines3: Reliable Reinforcement Learning Implementations. JMLR 22(268):1–8, 2021; https://stable-baselines3.readthedocs.io/en/master/guide/algos.html ; …/guide/install.html ; https://pypi.org/project/stable-baselines3/ | PPO actions Box/Discrete/MultiDiscrete/MultiBinary; DQN Discrete only; single-level Dict observations; requires Python 3.10+ and PyTorch ≥ 2.8; 2.9.2 |
| sb3-contrib | https://sb3-contrib.readthedocs.io/en/master/ (MaskablePPO, RecurrentPPO pages) | "Experimental code"; MaskablePPO masks Discrete/MultiDiscrete/MultiBinary, no recurrent policies; RecurrentPPO: MlpLstmPolicy/CnnLstmPolicy/MultiInputLstmPolicy, no Dict actions; QR-DQN available |
| Liang2018 | E. Liang et al. RLlib: Abstractions for Distributed Reinforcement Learning. arXiv:1712.09381 (ICML 2018); https://docs.ray.io/en/latest/ray-overview/installation.html | "Ray on Windows is currently in beta" |
| Huang2021 | S. Huang, R. F. J. Dossa, C. Ye, J. Braga. CleanRL: High-quality Single-file Implementations of Deep Reinforcement Learning Algorithms. arXiv:2111.08819; https://github.com/vwxyzjn/cleanrl | "not a modular library … not meant to be imported"; MIT; README lists Python < 3.11 |
| Wolf2019 | T. Wolf et al. HuggingFace's Transformers: State-of-the-art Natural Language Processing. arXiv:1910.03771; https://huggingface.co/docs/transformers/model_doc/decision_transformer | `DecisionTransformerModel` for vector states |
