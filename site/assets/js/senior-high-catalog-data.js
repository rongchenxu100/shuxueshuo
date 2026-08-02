window.__SENIOR_HIGH_CATALOG__ = {
  "version": 1,
  "chapters": [
    {
      "id": "sets",
      "label": "集合",
      "symbol": "{ }",
      "order": 5,
      "sections": [
        {
          "id": "set-concepts-and-representation",
          "label": "集合的概念和表示",
          "order": 10,
          "presentation": "learning",
          "topicId": "set-concepts-and-representation"
        }
      ]
    },
    {
      "id": "functions",
      "label": "函数",
      "symbol": "f(x)",
      "order": 10,
      "sections": [
        {
          "id": "function-concepts-and-representation",
          "label": "函数的概念",
          "order": 10,
          "presentation": "worksheet",
          "defaultCollectionId": "function-concepts-foundation",
          "collectionIds": [
            "function-concepts-foundation",
            "function-concepts-advanced"
          ]
        },
        {
          "id": "function-representation",
          "label": "函数的表示法",
          "order": 20,
          "presentation": "worksheet",
          "defaultCollectionId": "function-representation-foundation",
          "collectionIds": [
            "function-representation-foundation"
          ]
        }
      ]
    },
    {
      "id": "sequences",
      "label": "数列",
      "symbol": "Σ",
      "order": 20,
      "sections": []
    },
    {
      "id": "trigonometry",
      "label": "三角函数",
      "symbol": "sin",
      "order": 30,
      "sections": []
    },
    {
      "id": "vectors",
      "label": "平面向量",
      "symbol": "→",
      "order": 40,
      "sections": []
    },
    {
      "id": "solid-geometry",
      "label": "立体几何",
      "symbol": "◇",
      "order": 50,
      "sections": []
    },
    {
      "id": "analytic-geometry",
      "label": "解析几何",
      "symbol": "◯",
      "order": 60,
      "sections": []
    },
    {
      "id": "derivative",
      "label": "导数",
      "symbol": "d/dx",
      "order": 70,
      "sections": [
        {
          "id": "derivative-concepts-and-calculation",
          "label": "基本概念和运算",
          "order": 10
        },
        {
          "id": "derivative-applications",
          "label": "导数应用",
          "order": 20
        }
      ]
    },
    {
      "id": "probability-statistics",
      "label": "概率统计",
      "symbol": "P",
      "order": 80,
      "sections": []
    }
  ],
  "problems": [
    {
      "id": "cn-2022-gaokao-jia-wen-20",
      "title": "2022 年全国甲卷文科第 20 题：导数与公切线",
      "chapterId": "derivative",
      "sectionId": "derivative-concepts-and-calculation",
      "knowledgePointIds": [
        "tangent-equation",
        "common-tangent",
        "derivative-calculation",
        "function-range",
        "parameter-range"
      ],
      "tags": [
        "切线方程",
        "公切线",
        "导数运算",
        "函数值域",
        "参数取值范围"
      ],
      "difficulty": 4,
      "source": {
        "year": 2022,
        "region": "全国",
        "examLabel": "全国甲卷文科",
        "questionNumber": "20",
        "score": 12
      },
      "updatedAt": "2026-07-14T00:00:00+08:00",
      "path": "problems/senior-high/cn/20/cn-2022-gaokao-jia-wen-20.html",
      "thumbnail": "assets/images/problem-thumbnails/cn-2022-gaokao-jia-wen-20.svg",
      "status": "published",
      "interactive": true
    },
    {
      "id": "cn-2022-new-gaokao-i-15",
      "title": "2022 年新高考 I 卷第 15 题：过原点的切线",
      "chapterId": "derivative",
      "sectionId": "derivative-applications",
      "knowledgePointIds": [
        "tangent-equation",
        "tangent-through-fixed-point",
        "tangent-count",
        "quadratic-discriminant",
        "parameter-range"
      ],
      "tags": [
        "切线方程",
        "过定点切线",
        "切线条数",
        "判别式",
        "参数取值范围"
      ],
      "difficulty": 3,
      "source": {
        "year": 2022,
        "region": "全国",
        "examLabel": "新高考 I 卷",
        "questionNumber": "15",
        "score": 5
      },
      "updatedAt": "2026-07-20T00:00:00+08:00",
      "path": "problems/senior-high/cn/15/cn-2022-new-gaokao-i-15.html",
      "thumbnail": "assets/images/problem-thumbnails/cn-2022-new-gaokao-i-15.svg",
      "status": "published",
      "interactive": true
    }
  ],
  "collections": [
    {
      "id": "function-concepts-foundation",
      "chapterId": "functions",
      "sectionId": "function-concepts-and-representation",
      "title": "函数的概念 · 基础练习",
      "label": "基础练习",
      "status": "published",
      "problemCount": 11,
      "groups": [
        {
          "id": "function-concept",
          "label": "函数概念",
          "problems": [
            {
              "id": "function-concepts-20260722-q01",
              "number": 1,
              "source": "2026 江苏苏州实验中学期中",
              "problem": {
                "lines": [
                  {
                    "text": "集合 A={x|0≤x≤4}，B={y|0≤y≤2}，下列不能表示从 A 到 B 的函数的是：",
                    "html": "集合 A={x|0≤x≤4}，B={y|0≤y≤2}，下列不能表示从 A 到 B 的函数的是："
                  },
                  {
                    "text": "A. \\(y=\\frac{x}{2}\\)　　B. \\(y=\\frac{x}{3}\\)　　C. \\(y=\\frac{2x}{3}\\)　　D. \\(y=\\sqrt{x}\\)",
                    "html": "A. <span class=\"inline-math\">y=<span class=\"math-fraction\"><span class=\"math-numerator\">x</span><span class=\"math-denominator\">2</span></span></span>　　B. <span class=\"inline-math\">y=<span class=\"math-fraction\"><span class=\"math-numerator\">x</span><span class=\"math-denominator\">3</span></span></span>　　C. <span class=\"inline-math\">y=<span class=\"math-fraction\"><span class=\"math-numerator\">2x</span><span class=\"math-denominator\">3</span></span></span>　　D. <span class=\"inline-math\">y=<span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">x</span></span></span>"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-concepts-and-representation/function-concepts-20260722-q01.html",
              "groupId": "function-concept",
              "groupLabel": "函数概念"
            },
            {
              "id": "function-concepts-20260722-q02",
              "number": 2,
              "problem": {
                "lines": [
                  {
                    "text": "下列各组函数表示同一个函数的是：",
                    "html": "下列各组函数表示同一个函数的是："
                  },
                  {
                    "text": "A. \\(f(x)=\\sqrt{-2x^3}\\)，\\(g(x)=x\\sqrt{-2x}\\)",
                    "html": "A. <span class=\"inline-math\">f(x)=<span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">-2x<sup>3</sup></span></span></span>，<span class=\"inline-math\">g(x)=x<span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">-2x</span></span></span>"
                  },
                  {
                    "text": "B. \\(f(x)=x\\)，\\(g(x)=\\frac{x^2}{x}\\)",
                    "html": "B. <span class=\"inline-math\">f(x)=x</span>，<span class=\"inline-math\">g(x)=<span class=\"math-fraction\"><span class=\"math-numerator\">x<sup>2</sup></span><span class=\"math-denominator\">x</span></span></span>"
                  },
                  {
                    "text": "C. \\(f(x)=x^2-2x-1\\)，\\(g(t)=t^2-2t-1\\)",
                    "html": "C. <span class=\"inline-math\">f(x)=x<sup>2</sup>-2x-1</span>，<span class=\"inline-math\">g(t)=t<sup>2</sup>-2t-1</span>"
                  },
                  {
                    "text": "D. \\(f(x)=\\sqrt{x-1}\\sqrt{x+1}\\)，\\(g(x)=\\sqrt{(x+1)(x-1)}\\)",
                    "html": "D. <span class=\"inline-math\">f(x)=<span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">x-1</span></span><span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">x+1</span></span></span>，<span class=\"inline-math\">g(x)=<span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">(x+1)(x-1)</span></span></span>"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-concepts-and-representation/function-concepts-20260722-q02.html",
              "groupId": "function-concept",
              "groupLabel": "函数概念"
            },
            {
              "id": "function-concepts-20260722-q03",
              "number": 3,
              "source": "2026 江西抚州期中",
              "problem": {
                "lines": [
                  {
                    "text": "设集合 M={x|0≤x≤2}，N={y|0≤y≤2}。在下面的 4 个图形中，能表示集合 M 到集合 N 的函数关系的是。",
                    "html": "设集合 M={x|0≤x≤2}，N={y|0≤y≤2}。在下面的 4 个图形中，能表示集合 M 到集合 N 的函数关系的是。"
                  },
                  {
                    "ariaLabel": "原题图①至图④",
                    "figures": [
                      {
                        "id": "relation-1",
                        "title": "①",
                        "ariaLabel": "图①：从原点到点（1，2）的线段",
                        "caption": ""
                      },
                      {
                        "id": "relation-2",
                        "title": "②",
                        "ariaLabel": "图②：从点（0，2）到点（2，0）的线段",
                        "caption": ""
                      },
                      {
                        "id": "relation-3",
                        "title": "③",
                        "ariaLabel": "图③：从原点到点（2，1）的线段",
                        "caption": ""
                      },
                      {
                        "id": "relation-4",
                        "title": "④",
                        "ariaLabel": "图④：从点（0，1）分别连到点（2，0）和点（2，2）",
                        "caption": ""
                      }
                    ]
                  },
                  {
                    "text": "A. ①②③④　　B. ①②③　　C. ②③　　D. ②④",
                    "html": "A. ①②③④　　B. ①②③　　C. ②③　　D. ②④"
                  }
                ]
              },
              "originalFigures": [
                {
                  "id": "relation-1",
                  "renderId": "function-concepts-20260722-q03--relation-1",
                  "kind": "relationPlot"
                },
                {
                  "id": "relation-2",
                  "renderId": "function-concepts-20260722-q03--relation-2",
                  "kind": "relationPlot"
                },
                {
                  "id": "relation-3",
                  "renderId": "function-concepts-20260722-q03--relation-3",
                  "kind": "relationPlot"
                },
                {
                  "id": "relation-4",
                  "renderId": "function-concepts-20260722-q03--relation-4",
                  "kind": "relationPlot"
                }
              ],
              "figureSpec": {
                "$schema": "../../schemas/function-spec.schema.json",
                "version": 1,
                "id": "function-concepts-20260722-q03",
                "parameter": {
                  "name": "x",
                  "initial": 1
                },
                "panels": [
                  {
                    "id": "function-concepts-20260722-q03--relation-1",
                    "kind": "relationPlot",
                    "title": "图①",
                    "viewport": {
                      "x": 0.08,
                      "y": 0.08,
                      "width": 0.84,
                      "height": 0.84
                    },
                    "domain": {
                      "minX": 0,
                      "maxX": 2,
                      "minY": 0,
                      "maxY": 2
                    },
                    "axisPadding": {
                      "minX": 0.12,
                      "maxX": 0.4,
                      "minY": 0.12,
                      "maxY": 0.4
                    },
                    "guidePoints": [
                      {
                        "x": 1,
                        "y": 2
                      }
                    ],
                    "segments": [
                      {
                        "id": "r1",
                        "x1": 0,
                        "y1": 0,
                        "x2": 1,
                        "y2": 2
                      }
                    ]
                  },
                  {
                    "id": "function-concepts-20260722-q03--relation-2",
                    "kind": "relationPlot",
                    "title": "图②",
                    "viewport": {
                      "x": 0.08,
                      "y": 0.08,
                      "width": 0.84,
                      "height": 0.84
                    },
                    "domain": {
                      "minX": 0,
                      "maxX": 2,
                      "minY": 0,
                      "maxY": 2
                    },
                    "axisPadding": {
                      "minX": 0.12,
                      "maxX": 0.4,
                      "minY": 0.12,
                      "maxY": 0.4
                    },
                    "segments": [
                      {
                        "id": "r2",
                        "x1": 0,
                        "y1": 2,
                        "x2": 2,
                        "y2": 0
                      }
                    ]
                  },
                  {
                    "id": "function-concepts-20260722-q03--relation-3",
                    "kind": "relationPlot",
                    "title": "图③",
                    "viewport": {
                      "x": 0.08,
                      "y": 0.08,
                      "width": 0.84,
                      "height": 0.84
                    },
                    "domain": {
                      "minX": 0,
                      "maxX": 2,
                      "minY": 0,
                      "maxY": 2
                    },
                    "axisPadding": {
                      "minX": 0.12,
                      "maxX": 0.4,
                      "minY": 0.12,
                      "maxY": 0.4
                    },
                    "guidePoints": [
                      {
                        "x": 2,
                        "y": 1
                      }
                    ],
                    "segments": [
                      {
                        "id": "r3",
                        "x1": 0,
                        "y1": 0,
                        "x2": 2,
                        "y2": 1
                      }
                    ]
                  },
                  {
                    "id": "function-concepts-20260722-q03--relation-4",
                    "kind": "relationPlot",
                    "title": "图④",
                    "viewport": {
                      "x": 0.08,
                      "y": 0.08,
                      "width": 0.84,
                      "height": 0.84
                    },
                    "domain": {
                      "minX": 0,
                      "maxX": 2,
                      "minY": 0,
                      "maxY": 2
                    },
                    "axisPadding": {
                      "minX": 0.12,
                      "maxX": 0.4,
                      "minY": 0.12,
                      "maxY": 0.4
                    },
                    "guidePoints": [
                      {
                        "x": 2,
                        "y": 2
                      }
                    ],
                    "segments": [
                      {
                        "id": "r4a",
                        "x1": 0,
                        "y1": 1,
                        "x2": 2,
                        "y2": 0
                      },
                      {
                        "id": "r4b",
                        "x1": 0,
                        "y1": 1,
                        "x2": 2,
                        "y2": 2
                      }
                    ]
                  }
                ]
              },
              "solutionPath": "problems/senior-high/functions/function-concepts-and-representation/function-concepts-20260722-q03.html",
              "groupId": "function-concept",
              "groupLabel": "函数概念"
            }
          ]
        },
        {
          "id": "function-domain",
          "label": "函数定义域",
          "problems": [
            {
              "id": "function-concepts-20260722-q04",
              "number": 4,
              "source": "2026 河北沧州期末",
              "problem": {
                "lines": [
                  {
                    "text": "函数 \\(f(x)=\\frac{(2x-1)^0}{\\sqrt{2-x}}\\) 的定义域为______。",
                    "html": "函数 <span class=\"inline-math\">f(x)=<span class=\"math-fraction\"><span class=\"math-numerator\">(2x-1)<sup>0</sup></span><span class=\"math-denominator\"><span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">2-x</span></span></span></span></span> 的定义域为______。"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-concepts-and-representation/function-concepts-20260722-q04.html",
              "groupId": "function-domain",
              "groupLabel": "函数定义域"
            },
            {
              "id": "function-concepts-20260722-q05",
              "number": 5,
              "problem": {
                "lines": [
                  {
                    "text": "函数 \\(f(x)=\\frac{\\sqrt{3x+11}}{x}\\) 的定义域为______。",
                    "html": "函数 <span class=\"inline-math\">f(x)=<span class=\"math-fraction\"><span class=\"math-numerator\"><span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">3x+11</span></span></span><span class=\"math-denominator\">x</span></span></span> 的定义域为______。"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-concepts-and-representation/function-concepts-20260722-q05.html",
              "groupId": "function-domain",
              "groupLabel": "函数定义域"
            },
            {
              "id": "function-concepts-20260722-q06",
              "number": 6,
              "source": "2026 四川成都实验外月考",
              "problem": {
                "lines": [
                  {
                    "text": "某小区有一块底边和该底边上的高均为 40 m 的锐角三角形空地，计划在空地内种植一边长为 x m 的矩形草坪。求草坪面积 S 关于 x 的函数关系；若面积不小于 336 m²，求 x 的取值范围。",
                    "html": "某小区有一块底边和该底边上的高均为 40 m 的锐角三角形空地，计划在空地内种植一边长为 x m 的矩形草坪。求草坪面积 S 关于 x 的函数关系；若面积不小于 336 m²，求 x 的取值范围。"
                  },
                  {
                    "ariaLabel": "原题中的三角形空地和矩形草坪示意图",
                    "figures": [
                      {
                        "id": "original-context",
                        "title": "",
                        "ariaLabel": "底边和高均为 40 米的三角形内接一边长为 x 米的矩形",
                        "caption": ""
                      }
                    ]
                  }
                ]
              },
              "originalFigures": [
                {
                  "id": "original-context",
                  "renderId": "function-concepts-20260722-q06--original-context",
                  "kind": "contextGeometry"
                }
              ],
              "figureSpec": {
                "$schema": "../../schemas/function-spec.schema.json",
                "version": 1,
                "id": "function-concepts-20260722-q06",
                "parameter": {
                  "name": "x",
                  "initial": 20
                },
                "bindings": [
                  {
                    "name": "otherSide",
                    "expr": "40-x"
                  },
                  {
                    "name": "area",
                    "expr": "x*(40-x)"
                  }
                ],
                "panels": [
                  {
                    "id": "function-concepts-20260722-q06--original-context",
                    "kind": "contextGeometry",
                    "title": "原题示意图",
                    "viewport": {
                      "x": 0.08,
                      "y": 0.08,
                      "width": 0.84,
                      "height": 0.84
                    },
                    "geometry": {
                      "points": [
                        {
                          "id": "oa",
                          "x": 0.12,
                          "y": 0.82
                        },
                        {
                          "id": "ob",
                          "x": 0.8,
                          "y": 0.82
                        },
                        {
                          "id": "oc",
                          "x": 0.46,
                          "y": 0.12
                        },
                        {
                          "id": "od",
                          "x": 0.29,
                          "y": 0.82
                        },
                        {
                          "id": "oe",
                          "x": 0.63,
                          "y": 0.82
                        },
                        {
                          "id": "of",
                          "x": 0.63,
                          "y": 0.47
                        },
                        {
                          "id": "og",
                          "x": 0.29,
                          "y": 0.47
                        },
                        {
                          "id": "obase-left",
                          "x": 0.12,
                          "y": 0.93
                        },
                        {
                          "id": "obase-right",
                          "x": 0.8,
                          "y": 0.93
                        },
                        {
                          "id": "oheight-top",
                          "x": 0.9,
                          "y": 0.12
                        },
                        {
                          "id": "oheight-bottom",
                          "x": 0.9,
                          "y": 0.82
                        }
                      ],
                      "polygons": [
                        {
                          "id": "original-triangle",
                          "pointIds": [
                            "oa",
                            "ob",
                            "oc"
                          ]
                        },
                        {
                          "id": "original-lawn",
                          "pointIds": [
                            "od",
                            "oe",
                            "of",
                            "og"
                          ]
                        }
                      ],
                      "dimensions": [
                        {
                          "id": "original-x",
                          "startPointId": "og",
                          "endPointId": "of",
                          "label": "x m",
                          "labelDy": -18
                        },
                        {
                          "id": "original-base",
                          "startPointId": "obase-left",
                          "endPointId": "obase-right",
                          "label": "40 m"
                        },
                        {
                          "id": "original-height",
                          "startPointId": "oheight-top",
                          "endPointId": "oheight-bottom",
                          "label": "40 m",
                          "labelDx": 32
                        }
                      ]
                    }
                  }
                ]
              },
              "solutionPath": "problems/senior-high/functions/function-concepts-and-representation/function-concepts-20260722-q06.html",
              "groupId": "function-domain",
              "groupLabel": "函数定义域"
            }
          ]
        },
        {
          "id": "function-value-and-range",
          "label": "函数值域",
          "problems": [
            {
              "id": "function-concepts-20260722-q07",
              "number": 7,
              "source": "2026 北京八一学校月考",
              "problem": {
                "lines": [
                  {
                    "text": "下列函数中，值域为 \\((0,+∞)\\) 的是：",
                    "html": "下列函数中，值域为 <span class=\"inline-math\">(0,+∞)</span> 的是："
                  },
                  {
                    "text": "A. \\(y=x+\\frac{1}{x}\\)　B. \\(y=x^2+x+1\\)　C. \\(y=\\frac{1}{x^2+1}\\)　D. \\(y=\\frac{1}{\\sqrt{x}}\\)",
                    "html": "A. <span class=\"inline-math\">y=x+<span class=\"math-fraction\"><span class=\"math-numerator\">1</span><span class=\"math-denominator\">x</span></span></span>　B. <span class=\"inline-math\">y=x<sup>2</sup>+x+1</span>　C. <span class=\"inline-math\">y=<span class=\"math-fraction\"><span class=\"math-numerator\">1</span><span class=\"math-denominator\">x<sup>2</sup>+1</span></span></span>　D. <span class=\"inline-math\">y=<span class=\"math-fraction\"><span class=\"math-numerator\">1</span><span class=\"math-denominator\"><span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">x</span></span></span></span></span>"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-concepts-and-representation/function-concepts-20260722-q07.html",
              "groupId": "function-value-and-range",
              "groupLabel": "函数值域"
            },
            {
              "id": "function-concepts-20260722-q08",
              "number": 8,
              "source": "2026 四川成都双流立格实验学校月考",
              "problem": {
                "lines": [
                  {
                    "text": "函数 G(n)=2n+1，n∈{1,2,3} 的值域是______。",
                    "html": "函数 G(n)=2n+1，n∈{1,2,3} 的值域是______。"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-concepts-and-representation/function-concepts-20260722-q08.html",
              "groupId": "function-value-and-range",
              "groupLabel": "函数值域"
            },
            {
              "id": "function-concepts-20260722-q09",
              "number": 9,
              "source": "2026 山东淄博实验中学月考",
              "problem": {
                "lines": [
                  {
                    "text": "已知函数 f(x) 的定义域为 R，且 f(x+y)+f(x−y)=f(x)f(y)，f(1)=−1，则 f(0)=______。",
                    "html": "已知函数 f(x) 的定义域为 R，且 f(x+y)+f(x−y)=f(x)f(y)，f(1)=−1，则 f(0)=______。"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-concepts-and-representation/function-concepts-20260722-q09.html",
              "groupId": "function-value-and-range",
              "groupLabel": "函数值域"
            },
            {
              "id": "function-concepts-20260722-q10",
              "number": 10,
              "source": "2026 四川巴中第三中学期中",
              "problem": {
                "lines": [
                  {
                    "text": "函数 \\(g(t)=-2t^2-t+4\\) 在 \\([0,+∞)\\) 上的值域为______。",
                    "html": "函数 <span class=\"inline-math\">g(t)=-2t<sup>2</sup>-t+4</span> 在 <span class=\"inline-math\">[0,+∞)</span> 上的值域为______。"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-concepts-and-representation/function-concepts-20260722-q10.html",
              "groupId": "function-value-and-range",
              "groupLabel": "函数值域"
            },
            {
              "id": "function-concepts-20260722-q11",
              "number": 11,
              "source": "2026 河南名校期中大联考",
              "problem": {
                "lines": [
                  {
                    "text": "函数 \\(f(x)=\\frac{x-1}{1+x}\\) 在区间 \\([\\frac{1}{2},2]\\) 上的值域为______。",
                    "html": "函数 <span class=\"inline-math\">f(x)=<span class=\"math-fraction\"><span class=\"math-numerator\">x-1</span><span class=\"math-denominator\">1+x</span></span></span> 在区间 <span class=\"inline-math\">[<span class=\"math-fraction\"><span class=\"math-numerator\">1</span><span class=\"math-denominator\">2</span></span>,2]</span> 上的值域为______。"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-concepts-and-representation/function-concepts-20260722-q11.html",
              "groupId": "function-value-and-range",
              "groupLabel": "函数值域"
            }
          ]
        }
      ]
    },
    {
      "id": "function-concepts-advanced",
      "chapterId": "functions",
      "sectionId": "function-concepts-and-representation",
      "title": "函数的概念 · 能力提升",
      "label": "能力提升",
      "status": "published",
      "problemCount": 13,
      "groups": [
        {
          "id": "function-concept",
          "label": "函数概念",
          "problems": [
            {
              "id": "function-concepts-advanced-20260726-q01",
              "number": 1,
              "source": "2026 广东东莞期末",
              "problem": {
                "lines": [
                  {
                    "text": "定义域为 R 的函数 \\(y=f(x)\\)，其图像与 \\(y\\) 轴的交点个数为（　）　A. 0　B. 1　C. 2　D. 不确定",
                    "html": "定义域为 R 的函数 <span class=\"inline-math\">y=f(x)</span>，其图像与 <span class=\"inline-math\">y</span> 轴的交点个数为（　）　A. 0　B. 1　C. 2　D. 不确定"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-concepts-and-representation/function-concepts-advanced-20260726-q01.html",
              "groupId": "function-concept",
              "groupLabel": "函数概念"
            },
            {
              "id": "function-concepts-advanced-20260726-q02",
              "number": 2,
              "source": "2025 河南郑州中学月考",
              "problem": {
                "lines": [
                  {
                    "text": "已知函数 \\(f(x)\\) 的定义域为 R，则下列等式可以成立的是（　）　A. \\(f(x^2)=x^3\\)　B. \\(f(x^2+1)=|x+1|\\)　C. \\(f(x^2+x)=|x|\\)　D. \\(f(|x|)=x^2+1\\)",
                    "html": "已知函数 <span class=\"inline-math\">f(x)</span> 的定义域为 R，则下列等式可以成立的是（　）　A. <span class=\"inline-math\">f(x<sup>2</sup>)=x<sup>3</sup></span>　B. <span class=\"inline-math\">f(x<sup>2</sup>+1)=|x+1|</span>　C. <span class=\"inline-math\">f(x<sup>2</sup>+x)=|x|</span>　D. <span class=\"inline-math\">f(|x|)=x<sup>2</sup>+1</span>"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-concepts-and-representation/function-concepts-advanced-20260726-q02.html",
              "groupId": "function-concept",
              "groupLabel": "函数概念"
            }
          ]
        },
        {
          "id": "function-domain",
          "label": "函数定义域",
          "problems": [
            {
              "id": "function-concepts-advanced-20260726-q03",
              "number": 3,
              "source": "2026 江苏泰州中学期中",
              "problem": {
                "lines": [
                  {
                    "text": "已知函数 \\(f(x+2)\\) 的定义域为 \\((-3,4)\\)，则函数 \\(g(x)=\\frac{f(x+1)}{\\sqrt{3x-1}}\\) 的定义域为（　）　A. \\((-4,3)\\)　B. \\((-2,5)\\)　C. \\((\\frac{1}{3},3)\\)　D. \\((\\frac{1}{3},5)\\)",
                    "html": "已知函数 <span class=\"inline-math\">f(x+2)</span> 的定义域为 <span class=\"inline-math\">(-3,4)</span>，则函数 <span class=\"inline-math\">g(x)=<span class=\"math-fraction\"><span class=\"math-numerator\">f(x+1)</span><span class=\"math-denominator\"><span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">3x-1</span></span></span></span></span> 的定义域为（　）　A. <span class=\"inline-math\">(-4,3)</span>　B. <span class=\"inline-math\">(-2,5)</span>　C. <span class=\"inline-math\">(<span class=\"math-fraction\"><span class=\"math-numerator\">1</span><span class=\"math-denominator\">3</span></span>,3)</span>　D. <span class=\"inline-math\">(<span class=\"math-fraction\"><span class=\"math-numerator\">1</span><span class=\"math-denominator\">3</span></span>,5)</span>"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-concepts-and-representation/function-concepts-advanced-20260726-q03.html",
              "groupId": "function-domain",
              "groupLabel": "函数定义域"
            },
            {
              "id": "function-concepts-advanced-20260726-q04",
              "number": 4,
              "source": "2025 黑龙江鹤岗第一中学期中",
              "problem": {
                "lines": [
                  {
                    "text": "已知函数 \\(f(x)=\\sqrt{ax^2-2ax+1}\\) 的定义域为 R，则实数 \\(a\\) 的取值范围是（　）　A. \\((0,1]\\)　B. \\((0,+∞)\\)　C. \\([1,+∞)\\)　D. \\([0,1]\\)",
                    "html": "已知函数 <span class=\"inline-math\">f(x)=<span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">ax<sup>2</sup>-2ax+1</span></span></span> 的定义域为 R，则实数 <span class=\"inline-math\">a</span> 的取值范围是（　）　A. <span class=\"inline-math\">(0,1]</span>　B. <span class=\"inline-math\">(0,+∞)</span>　C. <span class=\"inline-math\">[1,+∞)</span>　D. <span class=\"inline-math\">[0,1]</span>"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-concepts-and-representation/function-concepts-advanced-20260726-q04.html",
              "groupId": "function-domain",
              "groupLabel": "函数定义域"
            },
            {
              "id": "function-concepts-advanced-20260726-q05",
              "number": 5,
              "source": "2026 广东珠海期中",
              "problem": {
                "lines": [
                  {
                    "text": "已知函数 \\(f(x)=x^2-2x-3\\) 的定义域为 \\([a,b]\\)，值域为 \\([-4,5]\\)，则实数对 \\((a,b)\\) 不可能为（　）　A. \\((-2,4)\\)　B. \\((-2,1)\\)　C. \\((1,4)\\)　D. \\((-1,1)\\)",
                    "html": "已知函数 <span class=\"inline-math\">f(x)=x<sup>2</sup>-2x-3</span> 的定义域为 <span class=\"inline-math\">[a,b]</span>，值域为 <span class=\"inline-math\">[-4,5]</span>，则实数对 <span class=\"inline-math\">(a,b)</span> 不可能为（　）　A. <span class=\"inline-math\">(-2,4)</span>　B. <span class=\"inline-math\">(-2,1)</span>　C. <span class=\"inline-math\">(1,4)</span>　D. <span class=\"inline-math\">(-1,1)</span>"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-concepts-and-representation/function-concepts-advanced-20260726-q05.html",
              "groupId": "function-domain",
              "groupLabel": "函数定义域"
            },
            {
              "id": "function-concepts-advanced-20260726-q06",
              "number": 6,
              "source": "2025 上海长宁段考",
              "problem": {
                "lines": [
                  {
                    "text": "已知函数 \\(f(x)=\\frac{1}{x-1}\\) 的值域为 \\((-1,0)∪(0,+∞)\\)，则函数 \\(f(x)\\) 的定义域为______。",
                    "html": "已知函数 <span class=\"inline-math\">f(x)=<span class=\"math-fraction\"><span class=\"math-numerator\">1</span><span class=\"math-denominator\">x-1</span></span></span> 的值域为 <span class=\"inline-math\">(-1,0)∪(0,+∞)</span>，则函数 <span class=\"inline-math\">f(x)</span> 的定义域为______。"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-concepts-and-representation/function-concepts-advanced-20260726-q06.html",
              "groupId": "function-domain",
              "groupLabel": "函数定义域"
            }
          ]
        },
        {
          "id": "function-value-and-range",
          "label": "函数值域",
          "problems": [
            {
              "id": "function-concepts-advanced-20260726-q07",
              "number": 7,
              "source": "2026 重庆八中期中",
              "problem": {
                "lines": [
                  {
                    "text": "函数 \\(f(x)=\\sqrt{x-2}-x\\)，\\(x∈(2,6]\\) 的值域为（　）　A. \\((−∞,-\\frac{7}{4}]\\)　B. \\([-4,-\\frac{7}{4}]\\)　C. \\([-4,-2]\\)　D. \\([-4,-2)\\)",
                    "html": "函数 <span class=\"inline-math\">f(x)=<span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">x-2</span></span>-x</span>，<span class=\"inline-math\">x∈(2,6]</span> 的值域为（　）　A. <span class=\"inline-math\">(−∞,-<span class=\"math-fraction\"><span class=\"math-numerator\">7</span><span class=\"math-denominator\">4</span></span>]</span>　B. <span class=\"inline-math\">[-4,-<span class=\"math-fraction\"><span class=\"math-numerator\">7</span><span class=\"math-denominator\">4</span></span>]</span>　C. <span class=\"inline-math\">[-4,-2]</span>　D. <span class=\"inline-math\">[-4,-2)</span>"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-concepts-and-representation/function-concepts-advanced-20260726-q07.html",
              "groupId": "function-value-and-range",
              "groupLabel": "函数值域"
            },
            {
              "id": "function-concepts-advanced-20260726-q08",
              "number": 8,
              "source": "2026 广东湛江八校联考",
              "problem": {
                "lines": [
                  {
                    "text": "若函数 \\(f(x)=\\frac{3x^2+x+3}{x^2+1}\\) 的最大值为 \\(a\\)，最小值为 \\(b\\)，则 \\(a+b=（　）\\)　A. 4　B. 6　C. 7　D. 8",
                    "html": "若函数 <span class=\"inline-math\">f(x)=<span class=\"math-fraction\"><span class=\"math-numerator\">3x<sup>2</sup>+x+3</span><span class=\"math-denominator\">x<sup>2</sup>+1</span></span></span> 的最大值为 <span class=\"inline-math\">a</span>，最小值为 <span class=\"inline-math\">b</span>，则 <span class=\"inline-math\">a+b=（　）</span>　A. 4　B. 6　C. 7　D. 8"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-concepts-and-representation/function-concepts-advanced-20260726-q08.html",
              "groupId": "function-value-and-range",
              "groupLabel": "函数值域"
            },
            {
              "id": "function-concepts-advanced-20260726-q09",
              "number": 9,
              "source": "2025 辽宁沈阳第一〇中学质量监测",
              "problem": {
                "lines": [
                  {
                    "text": "已知函数 \\(f(x)=\\frac{1}{x}\\)（\\(1≤x≤2\\)），则函数 \\(g(x)=2f(x)+f(x^2)\\) 的值域为（　）　A. \\([3,2+2\\sqrt{2}]\\)　B. \\([\\frac{5}{4},3]\\)　C. \\([\\frac{9}{16},3]\\)　D. \\([\\frac{1}{2}+\\sqrt{2},3]\\)",
                    "html": "已知函数 <span class=\"inline-math\">f(x)=<span class=\"math-fraction\"><span class=\"math-numerator\">1</span><span class=\"math-denominator\">x</span></span></span>（<span class=\"inline-math\">1≤x≤2</span>），则函数 <span class=\"inline-math\">g(x)=2f(x)+f(x<sup>2</sup>)</span> 的值域为（　）　A. <span class=\"inline-math\">[3,2+2<span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">2</span></span>]</span>　B. <span class=\"inline-math\">[<span class=\"math-fraction\"><span class=\"math-numerator\">5</span><span class=\"math-denominator\">4</span></span>,3]</span>　C. <span class=\"inline-math\">[<span class=\"math-fraction\"><span class=\"math-numerator\">9</span><span class=\"math-denominator\">16</span></span>,3]</span>　D. <span class=\"inline-math\">[<span class=\"math-fraction\"><span class=\"math-numerator\">1</span><span class=\"math-denominator\">2</span></span>+<span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">2</span></span>,3]</span>"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-concepts-and-representation/function-concepts-advanced-20260726-q09.html",
              "groupId": "function-value-and-range",
              "groupLabel": "函数值域"
            },
            {
              "id": "function-concepts-advanced-20260726-q10",
              "number": 10,
              "source": "2026 江苏百校大联考",
              "problem": {
                "lines": [
                  {
                    "text": "函数 \\(f(x)=\\sqrt{1-x}+\\sqrt{1+x}\\) 的值域是（　）　A. \\([0,2]\\)　B. \\([1,2]\\)　C. \\([\\sqrt{2},2]\\)　D. \\([2,+∞)\\)",
                    "html": "函数 <span class=\"inline-math\">f(x)=<span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">1-x</span></span>+<span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">1+x</span></span></span> 的值域是（　）　A. <span class=\"inline-math\">[0,2]</span>　B. <span class=\"inline-math\">[1,2]</span>　C. <span class=\"inline-math\">[<span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">2</span></span>,2]</span>　D. <span class=\"inline-math\">[2,+∞)</span>"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-concepts-and-representation/function-concepts-advanced-20260726-q10.html",
              "groupId": "function-value-and-range",
              "groupLabel": "函数值域"
            },
            {
              "id": "function-concepts-advanced-20260726-q11",
              "number": 11,
              "source": "2026 山东日照第一中学月考",
              "problem": {
                "lines": [
                  {
                    "text": "已知函数 \\(f(x)\\) 的定义域为 R，若 \\(f(x-2)=f(x+4)-6\\)，\\(f(3)=2\\)，则 \\(f(2025)=______\\)。",
                    "html": "已知函数 <span class=\"inline-math\">f(x)</span> 的定义域为 R，若 <span class=\"inline-math\">f(x-2)=f(x+4)-6</span>，<span class=\"inline-math\">f(3)=2</span>，则 <span class=\"inline-math\">f(2025)=______</span>。"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-concepts-and-representation/function-concepts-advanced-20260726-q11.html",
              "groupId": "function-value-and-range",
              "groupLabel": "函数值域"
            },
            {
              "id": "function-concepts-advanced-20260726-q12",
              "number": 12,
              "source": "2026 山东省实验中学期中",
              "problem": {
                "lines": [
                  {
                    "text": "已知函数 \\(f(x)=x-1\\)，\\(g(x)=kx^2-(2k+1)x+k+1\\)，其中 \\(k>1\\)。若对任意 \\(x_1∈[2,4]\\)，存在 \\(x_2∈[2,4]\\)，使得 \\(f(x_1)f(x_2)=g(x_1)g(x_2)\\) 成立，则实数 \\(k\\) 的值等于______。",
                    "html": "已知函数 <span class=\"inline-math\">f(x)=x-1</span>，<span class=\"inline-math\">g(x)=kx<sup>2</sup>-(2k+1)x+k+1</span>，其中 <span class=\"inline-math\">k&gt;1</span>。若对任意 <span class=\"inline-math\">x<sub>1</sub>∈[2,4]</span>，存在 <span class=\"inline-math\">x<sub>2</sub>∈[2,4]</span>，使得 <span class=\"inline-math\">f(x<sub>1</sub>)f(x<sub>2</sub>)=g(x<sub>1</sub>)g(x<sub>2</sub>)</span> 成立，则实数 <span class=\"inline-math\">k</span> 的值等于______。"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-concepts-and-representation/function-concepts-advanced-20260726-q12.html",
              "groupId": "function-value-and-range",
              "groupLabel": "函数值域"
            }
          ]
        },
        {
          "id": "function-comprehensive",
          "label": "函数综合应用",
          "problems": [
            {
              "id": "function-concepts-advanced-20260726-q13",
              "number": 13,
              "source": "2026 山西大同期中",
              "problem": {
                "lines": [
                  {
                    "text": "下图是由两个高为 H 的圆锥（去掉底面）构成的玻璃容器，装满水，其底部装有一个排水小孔。当小孔打开时，水从孔中匀速流出，在 t 时刻，水面的高度为 h，水面对应圆的直径为 d，则下列说法错误的是（　）　A. h 是 d 的函数　B. d 是 t 的函数　C. h 是 t 的函数　D. d 是 h 的函数",
                    "html": "下图是由两个高为 H 的圆锥（去掉底面）构成的玻璃容器，装满水，其底部装有一个排水小孔。当小孔打开时，水从孔中匀速流出，在 t 时刻，水面的高度为 h，水面对应圆的直径为 d，则下列说法错误的是（　）　A. h 是 d 的函数　B. d 是 t 的函数　C. h 是 t 的函数　D. d 是 h 的函数"
                  },
                  {
                    "ariaLabel": "原题中的双圆锥玻璃容器示意图",
                    "figures": [
                      {
                        "id": "original-container",
                        "title": "",
                        "ariaLabel": "两个等高圆锥组成的排水容器",
                        "caption": ""
                      }
                    ]
                  }
                ]
              },
              "originalFigures": [
                {
                  "id": "original-container",
                  "renderId": "function-concepts-advanced-20260726-q13--original-container",
                  "kind": "contextGeometry"
                }
              ],
              "figureSpec": {
                "$schema": "../../schemas/function-spec.schema.json",
                "version": 1,
                "id": "function-concepts-advanced-20260726-q13",
                "panels": [
                  {
                    "id": "function-concepts-advanced-20260726-q13--original-container",
                    "kind": "contextGeometry",
                    "title": "双圆锥玻璃容器",
                    "viewport": {
                      "x": 0.2,
                      "y": 0.05,
                      "width": 0.6,
                      "height": 0.9
                    },
                    "geometry": {
                      "points": [
                        {
                          "id": "top",
                          "x": 0.5,
                          "y": 0.08,
                          "label": "上顶点"
                        },
                        {
                          "id": "left-mid",
                          "x": 0.2,
                          "y": 0.48
                        },
                        {
                          "id": "right-mid",
                          "x": 0.8,
                          "y": 0.48
                        },
                        {
                          "id": "join-center",
                          "x": 0.5,
                          "y": 0.48
                        },
                        {
                          "id": "bottom",
                          "x": 0.5,
                          "y": 0.9,
                          "label": "排水孔"
                        },
                        {
                          "id": "water-left",
                          "x": 0.34,
                          "y": 0.3
                        },
                        {
                          "id": "water-right",
                          "x": 0.66,
                          "y": 0.3
                        },
                        {
                          "id": "water-center",
                          "x": 0.5,
                          "y": 0.3
                        },
                        {
                          "id": "height-bottom",
                          "x": 0.88,
                          "y": 0.9
                        },
                        {
                          "id": "height-top",
                          "x": 0.88,
                          "y": 0.3
                        }
                      ],
                      "polygons": [
                        {
                          "id": "upper-water",
                          "pointIds": [
                            "water-left",
                            "water-right",
                            "right-mid",
                            "left-mid"
                          ],
                          "fill": "#bae6fd",
                          "stroke": "none",
                          "strokeWidth": 0
                        },
                        {
                          "id": "lower-water",
                          "pointIds": [
                            "left-mid",
                            "right-mid",
                            "bottom"
                          ],
                          "fill": "#bae6fd",
                          "stroke": "none",
                          "strokeWidth": 0
                        },
                        {
                          "id": "upper-cone",
                          "pointIds": [
                            "top",
                            "left-mid",
                            "right-mid"
                          ],
                          "fill": "none"
                        },
                        {
                          "id": "lower-cone",
                          "pointIds": [
                            "left-mid",
                            "right-mid",
                            "bottom"
                          ],
                          "fill": "none"
                        }
                      ],
                      "ellipses": [
                        {
                          "id": "joined-rim",
                          "centerPointId": "join-center",
                          "rx": 0.3,
                          "ry": 0.045,
                          "fill": "#bae6fd",
                          "stroke": "#0f766e",
                          "backHalfDashed": true
                        },
                        {
                          "id": "water-surface",
                          "centerPointId": "water-center",
                          "rx": 0.16,
                          "ry": 0.028,
                          "fill": "#bae6fd",
                          "stroke": "#0284c7",
                          "backHalfDashed": true
                        }
                      ],
                      "dimensions": [
                        {
                          "id": "diameter",
                          "startPointId": "water-left",
                          "endPointId": "water-right",
                          "label": "d",
                          "dashed": true,
                          "labelDy": -18
                        },
                        {
                          "id": "height",
                          "startPointId": "height-bottom",
                          "endPointId": "height-top",
                          "label": "h",
                          "labelDx": 28
                        }
                      ]
                    }
                  }
                ]
              },
              "solutionPath": "problems/senior-high/functions/function-concepts-and-representation/function-concepts-advanced-20260726-q13.html",
              "groupId": "function-comprehensive",
              "groupLabel": "函数综合应用"
            }
          ]
        }
      ]
    },
    {
      "id": "function-representation-foundation",
      "chapterId": "functions",
      "sectionId": "function-representation",
      "title": "函数的表示法 · 基础练习",
      "label": "表示法基础",
      "status": "published",
      "problemCount": 13,
      "groups": [
        {
          "id": "function-value-and-range",
          "label": "图象法和列表法",
          "problems": [
            {
              "id": "function-representation-20260727-q01",
              "number": 1,
              "source": "2026 陕西咸阳期中",
              "problem": {
                "lines": [
                  {
                    "text": "函数 \\(y=f(x)\\) 由下表给出，则 \\(f(f(4)-2)\\) 的值为（　）",
                    "html": "函数 <span class=\"inline-math\">y=f(x)</span> 由下表给出，则 <span class=\"inline-math\">f(f(4)-2)</span> 的值为（　）"
                  },
                  {
                    "ariaLabel": "函数 f(x) 的列表",
                    "figures": [
                      {
                        "id": "function-table",
                        "title": "",
                        "ariaLabel": "x 分别处于三个区间时，f(x) 分别等于 1、2、3",
                        "caption": ""
                      }
                    ]
                  },
                  {
                    "text": "A. 1　　B. 2　　C. 3　　D. 4",
                    "html": "A. 1　　B. 2　　C. 3　　D. 4"
                  }
                ]
              },
              "originalFigures": [
                {
                  "id": "function-table",
                  "renderId": "function-representation-20260727-q01--function-table",
                  "kind": "valueTable"
                }
              ],
              "figureSpec": {
                "$schema": "../../schemas/function-spec.schema.json",
                "version": 1,
                "id": "function-representation-20260727-q01",
                "panels": [
                  {
                    "id": "function-representation-20260727-q01--function-table",
                    "kind": "valueTable",
                    "title": "函数 f(x) 的列表表示",
                    "viewport": {
                      "x": 0.06,
                      "y": 0.18,
                      "width": 0.88,
                      "height": 0.64
                    },
                    "columns": [
                      "x",
                      "x≤0",
                      "0<x<2",
                      "x≥2"
                    ],
                    "rows": [
                      {
                        "id": "row-f",
                        "cells": [
                          "f(x)",
                          "1",
                          "2",
                          "3"
                        ]
                      }
                    ]
                  }
                ]
              },
              "solutionPath": "problems/senior-high/functions/function-representation/function-representation-20260727-q01.html",
              "groupId": "function-value-and-range",
              "groupLabel": "图象法和列表法"
            },
            {
              "id": "function-representation-20260727-q02",
              "number": 2,
              "source": "2026 山西阳泉期末",
              "problem": {
                "lines": [
                  {
                    "text": "函数 \\(f(x)=x^2-2|x|\\) 的大致图象是（　）",
                    "html": "函数 <span class=\"inline-math\">f(x)=x<sup>2</sup>-2|x|</span> 的大致图象是（　）"
                  },
                  {
                    "ariaLabel": "四个候选函数图象",
                    "figures": [
                      {
                        "id": "option-a",
                        "title": "A",
                        "ariaLabel": "开口向上且顶点在 x 等于 1 的抛物线",
                        "caption": ""
                      },
                      {
                        "id": "option-b",
                        "title": "B",
                        "ariaLabel": "开口向上且顶点在 x 等于负 1 的抛物线",
                        "caption": ""
                      },
                      {
                        "id": "option-c",
                        "title": "C",
                        "ariaLabel": "关于 y 轴对称并有两个最低点的 W 形图象",
                        "caption": ""
                      },
                      {
                        "id": "option-d",
                        "title": "D",
                        "ariaLabel": "顶点在原点的抛物线",
                        "caption": ""
                      }
                    ]
                  },
                  {
                    "text": "A. 图 A　　B. 图 B　　C. 图 C　　D. 图 D",
                    "html": "A. 图 A　　B. 图 B　　C. 图 C　　D. 图 D"
                  }
                ]
              },
              "originalFigures": [
                {
                  "id": "option-a",
                  "renderId": "function-representation-20260727-q02--option-a",
                  "kind": "functionGraph"
                },
                {
                  "id": "option-b",
                  "renderId": "function-representation-20260727-q02--option-b",
                  "kind": "functionGraph"
                },
                {
                  "id": "option-c",
                  "renderId": "function-representation-20260727-q02--option-c",
                  "kind": "functionGraph"
                },
                {
                  "id": "option-d",
                  "renderId": "function-representation-20260727-q02--option-d",
                  "kind": "functionGraph"
                }
              ],
              "figureSpec": {
                "$schema": "../../schemas/function-spec.schema.json",
                "version": 1,
                "id": "function-representation-20260727-q02",
                "parameter": {
                  "name": "x",
                  "initial": 0
                },
                "panels": [
                  {
                    "id": "function-representation-20260727-q02--option-a",
                    "kind": "functionGraph",
                    "title": "A",
                    "viewport": {
                      "x": 0.08,
                      "y": 0.08,
                      "width": 0.84,
                      "height": 0.84
                    },
                    "domain": {
                      "minX": -2.8,
                      "maxX": 2.8,
                      "minY": -1.5,
                      "maxY": 3.2
                    },
                    "gridStepX": 1,
                    "gridStepY": 1,
                    "showAxisTicks": true,
                    "function": {
                      "variable": "x",
                      "expr": "x^2-2*x",
                      "label": "A",
                      "intervals": [
                        {
                          "min": -2.8,
                          "max": 2.8
                        }
                      ]
                    }
                  },
                  {
                    "id": "function-representation-20260727-q02--option-b",
                    "kind": "functionGraph",
                    "title": "B",
                    "viewport": {
                      "x": 0.08,
                      "y": 0.08,
                      "width": 0.84,
                      "height": 0.84
                    },
                    "domain": {
                      "minX": -2.8,
                      "maxX": 2.8,
                      "minY": -1.5,
                      "maxY": 3.2
                    },
                    "gridStepX": 1,
                    "gridStepY": 1,
                    "showAxisTicks": true,
                    "function": {
                      "variable": "x",
                      "expr": "x^2+2*x",
                      "label": "B",
                      "intervals": [
                        {
                          "min": -2.8,
                          "max": 2.8
                        }
                      ]
                    }
                  },
                  {
                    "id": "function-representation-20260727-q02--option-c",
                    "kind": "functionGraph",
                    "title": "C",
                    "viewport": {
                      "x": 0.08,
                      "y": 0.08,
                      "width": 0.84,
                      "height": 0.84
                    },
                    "domain": {
                      "minX": -2.8,
                      "maxX": 2.8,
                      "minY": -1.5,
                      "maxY": 3.2
                    },
                    "gridStepX": 1,
                    "gridStepY": 1,
                    "showAxisTicks": true,
                    "function": {
                      "variable": "x",
                      "expr": "x^2-2*abs(x)",
                      "label": "C",
                      "intervals": [
                        {
                          "min": -2.8,
                          "max": 2.8
                        }
                      ]
                    }
                  },
                  {
                    "id": "function-representation-20260727-q02--option-d",
                    "kind": "functionGraph",
                    "title": "D",
                    "viewport": {
                      "x": 0.08,
                      "y": 0.08,
                      "width": 0.84,
                      "height": 0.84
                    },
                    "domain": {
                      "minX": -2.8,
                      "maxX": 2.8,
                      "minY": -1.5,
                      "maxY": 3.2
                    },
                    "gridStepX": 1,
                    "gridStepY": 1,
                    "showAxisTicks": true,
                    "function": {
                      "variable": "x",
                      "expr": "x^2",
                      "label": "D",
                      "intervals": [
                        {
                          "min": -2.8,
                          "max": 2.8
                        }
                      ]
                    }
                  }
                ]
              },
              "solutionPath": "problems/senior-high/functions/function-representation/function-representation-20260727-q02.html",
              "groupId": "function-value-and-range",
              "groupLabel": "图象法和列表法"
            },
            {
              "id": "function-representation-20260727-q03",
              "number": 3,
              "problem": {
                "lines": [
                  {
                    "text": "用列表法表示 \\(f(x)\\) 如下表，则 \\(f(x)\\) 的解析式为______。",
                    "html": "用列表法表示 <span class=\"inline-math\">f(x)</span> 如下表，则 <span class=\"inline-math\">f(x)</span> 的解析式为______。"
                  },
                  {
                    "ariaLabel": "x 与 f(x) 的对应值表",
                    "figures": [
                      {
                        "id": "original-table",
                        "title": "",
                        "ariaLabel": "x 为 1 到 5 时，f(x) 依次为 6、12、18、24、30",
                        "caption": ""
                      }
                    ]
                  },
                  {
                    "text": "填写解析式。",
                    "html": "填写解析式。"
                  }
                ]
              },
              "originalFigures": [
                {
                  "id": "original-table",
                  "renderId": "function-representation-20260727-q03--original-table",
                  "kind": "valueTable"
                }
              ],
              "figureSpec": {
                "$schema": "../../schemas/function-spec.schema.json",
                "version": 1,
                "id": "function-representation-20260727-q03",
                "panels": [
                  {
                    "id": "function-representation-20260727-q03--original-table",
                    "kind": "valueTable",
                    "title": "函数 f(x) 的列表表示",
                    "viewport": {
                      "x": 0.05,
                      "y": 0.18,
                      "width": 0.9,
                      "height": 0.64
                    },
                    "columns": [
                      "x",
                      "1",
                      "2",
                      "3",
                      "4",
                      "5"
                    ],
                    "rows": [
                      {
                        "id": "original-outputs",
                        "cells": [
                          "f(x)",
                          "6",
                          "12",
                          "18",
                          "24",
                          "30"
                        ]
                      }
                    ]
                  }
                ]
              },
              "solutionPath": "problems/senior-high/functions/function-representation/function-representation-20260727-q03.html",
              "groupId": "function-value-and-range",
              "groupLabel": "图象法和列表法"
            }
          ]
        },
        {
          "id": "function-concept",
          "label": "函数的解析式",
          "problems": [
            {
              "id": "function-representation-20260727-q04",
              "number": 4,
              "source": "2026 吉林长春东北师大附中月考",
              "problem": {
                "lines": [
                  {
                    "text": "已知 \\(f(x^2+1)=x^4-1\\)，则函数 \\(f(x)\\) 的解析式为（　）　A. \\(f(x)=x^2-2x\\)　B. \\(f(x)=x^2-1\\)（\\(x≥1\\)）　C. \\(f(x)=x^2-2x+2\\)（\\(x≥1\\)）　D. \\(f(x)=x^2-2x\\)（\\(x≥1\\)）",
                    "html": "已知 <span class=\"inline-math\">f(x<sup>2</sup>+1)=x<sup>4</sup>-1</span>，则函数 <span class=\"inline-math\">f(x)</span> 的解析式为（　）　A. <span class=\"inline-math\">f(x)=x<sup>2</sup>-2x</span>　B. <span class=\"inline-math\">f(x)=x<sup>2</sup>-1</span>（<span class=\"inline-math\">x≥1</span>）　C. <span class=\"inline-math\">f(x)=x<sup>2</sup>-2x+2</span>（<span class=\"inline-math\">x≥1</span>）　D. <span class=\"inline-math\">f(x)=x<sup>2</sup>-2x</span>（<span class=\"inline-math\">x≥1</span>）"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-representation/function-representation-20260727-q04.html",
              "groupId": "function-concept",
              "groupLabel": "函数的解析式"
            },
            {
              "id": "function-representation-20260727-q05",
              "number": 5,
              "source": "2026 山东滕州第一中学月考",
              "problem": {
                "lines": [
                  {
                    "text": "若函数 \\(y=f(x)\\) 满足 \\(2\\sqrt{x}f(\\frac{1}{x})-f(x)=3x\\)，则 \\(f(\\frac{1}{4})=\\)______。",
                    "html": "若函数 <span class=\"inline-math\">y=f(x)</span> 满足 <span class=\"inline-math\">2<span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">x</span></span>f(<span class=\"math-fraction\"><span class=\"math-numerator\">1</span><span class=\"math-denominator\">x</span></span>)-f(x)=3x</span>，则 <span class=\"inline-math\">f(<span class=\"math-fraction\"><span class=\"math-numerator\">1</span><span class=\"math-denominator\">4</span></span>)=</span>______。"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-representation/function-representation-20260727-q05.html",
              "groupId": "function-concept",
              "groupLabel": "函数的解析式"
            },
            {
              "id": "function-representation-20260727-q06",
              "number": 6,
              "source": "2026 福建宁德期末",
              "problem": {
                "lines": [
                  {
                    "text": "已知函数 \\(f(x)\\) 满足：对任意实数 \\(x,y\\)，都有 \\(f(x+y)=f(x)+f(y)+1\\) 成立，写出函数 \\(f(x)\\) 的一个解析式：______。",
                    "html": "已知函数 <span class=\"inline-math\">f(x)</span> 满足：对任意实数 <span class=\"inline-math\">x,y</span>，都有 <span class=\"inline-math\">f(x+y)=f(x)+f(y)+1</span> 成立，写出函数 <span class=\"inline-math\">f(x)</span> 的一个解析式：______。"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-representation/function-representation-20260727-q06.html",
              "groupId": "function-concept",
              "groupLabel": "函数的解析式"
            },
            {
              "id": "function-representation-20260727-q07",
              "number": 7,
              "source": "2026 河南安阳第一中学月考",
              "problem": {
                "lines": [
                  {
                    "text": "求下列函数 \\(f(x)\\) 的解析式：",
                    "html": "求下列函数 <span class=\"inline-math\">f(x)</span> 的解析式："
                  },
                  {
                    "text": "（1）已知函数 \\(f(x)\\) 满足 \\(f(\\sqrt{x}+1)=x+2\\sqrt{x}+1\\)；",
                    "html": "（1）已知函数 <span class=\"inline-math\">f(x)</span> 满足 <span class=\"inline-math\">f(<span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">x</span></span>+1)=x+2<span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">x</span></span>+1</span>；"
                  },
                  {
                    "text": "（2）已知一次函数 \\(f(x)\\) 在 R 上满足 \\(f(f(x))=4x+6\\)；",
                    "html": "（2）已知一次函数 <span class=\"inline-math\">f(x)</span> 在 R 上满足 <span class=\"inline-math\">f(f(x))=4x+6</span>；"
                  },
                  {
                    "text": "（3）已知函数 \\(f(x)\\) 满足 \\(2f(x)-f(-x)=x+1\\)。",
                    "html": "（3）已知函数 <span class=\"inline-math\">f(x)</span> 满足 <span class=\"inline-math\">2f(x)-f(-x)=x+1</span>。"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-representation/function-representation-20260727-q07.html",
              "groupId": "function-concept",
              "groupLabel": "函数的解析式"
            }
          ]
        },
        {
          "id": "function-comprehensive",
          "label": "分段函数与综合应用",
          "problems": [
            {
              "id": "function-representation-20260727-q08",
              "number": 8,
              "source": "2026 重庆渝东九校期中联考",
              "problem": {
                "lines": [
                  {
                    "text": "已知二次函数 \\(f(x)\\) 满足 \\(f(0)=0\\)，\\(f(x+1)-f(x)=2x-3\\)。",
                    "html": "已知二次函数 <span class=\"inline-math\">f(x)</span> 满足 <span class=\"inline-math\">f(0)=0</span>，<span class=\"inline-math\">f(x+1)-f(x)=2x-3</span>。"
                  },
                  {
                    "text": "（1）求二次函数 \\(f(x)\\) 的解析式；",
                    "html": "（1）求二次函数 <span class=\"inline-math\">f(x)</span> 的解析式；"
                  },
                  {
                    "text": "（2）求不等式 \\(f(x)≥18-x\\) 的解集。",
                    "html": "（2）求不等式 <span class=\"inline-math\">f(x)≥18-x</span> 的解集。"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-representation/function-representation-20260727-q08.html",
              "groupId": "function-comprehensive",
              "groupLabel": "分段函数与综合应用"
            },
            {
              "id": "function-representation-20260727-q09",
              "number": 9,
              "source": "2026 安徽桐城中学期末",
              "problem": {
                "lines": [
                  {
                    "text": "为了保护水资源、提倡节约用水，某市对居民生活用水实行“阶梯水价”，计费方法如下表。",
                    "html": "为了保护水资源、提倡节约用水，某市对居民生活用水实行“阶梯水价”，计费方法如下表。"
                  },
                  {
                    "ariaLabel": "居民生活用水阶梯水价表",
                    "figures": [
                      {
                        "id": "tariff-table",
                        "title": "",
                        "ariaLabel": "三档用水量及对应的每立方米价格",
                        "caption": ""
                      }
                    ]
                  },
                  {
                    "text": "若某户居民某月的用水量为 \\(x\\) m³，其缴纳的水费为 \\(y\\) 元，则以下结论正确的是（　）　A. \\(y=3x\\)（\\(0＜x≤12\\)），\\(y=6x\\)（\\(12＜x≤18\\)），\\(y=9x\\)（\\(x＞18\\)）　B. 当 \\(x=13\\) 时，\\(y=78\\)　C. 若 \\(y=48\\)，则 \\(x=14\\)　D. 若 \\(y=81\\)，则 \\(x=13.5\\)",
                    "html": "若某户居民某月的用水量为 <span class=\"inline-math\">x</span> m³，其缴纳的水费为 <span class=\"inline-math\">y</span> 元，则以下结论正确的是（　）　A. <span class=\"inline-math\">y=3x</span>（<span class=\"inline-math\">0＜x≤12</span>），<span class=\"inline-math\">y=6x</span>（<span class=\"inline-math\">12＜x≤18</span>），<span class=\"inline-math\">y=9x</span>（<span class=\"inline-math\">x＞18</span>）　B. 当 <span class=\"inline-math\">x=13</span> 时，<span class=\"inline-math\">y=78</span>　C. 若 <span class=\"inline-math\">y=48</span>，则 <span class=\"inline-math\">x=14</span>　D. 若 <span class=\"inline-math\">y=81</span>，则 <span class=\"inline-math\">x=13.5</span>"
                  }
                ]
              },
              "originalFigures": [
                {
                  "id": "tariff-table",
                  "renderId": "function-representation-20260727-q09--tariff-table",
                  "kind": "valueTable"
                }
              ],
              "figureSpec": {
                "$schema": "../../schemas/function-spec.schema.json",
                "version": 1,
                "id": "function-representation-20260727-q09",
                "parameter": {
                  "name": "x",
                  "initial": 14
                },
                "panels": [
                  {
                    "id": "function-representation-20260727-q09--tariff-table",
                    "kind": "valueTable",
                    "title": "居民生活用水阶梯水价",
                    "viewport": {
                      "x": 0.04,
                      "y": 0.12,
                      "width": 0.92,
                      "height": 0.76
                    },
                    "columns": [
                      "每户每月用水量",
                      "水价"
                    ],
                    "rows": [
                      {
                        "id": "tier-1",
                        "cells": [
                          "不超过 12 m³ 的部分",
                          "3 元/m³"
                        ]
                      },
                      {
                        "id": "tier-2",
                        "cells": [
                          "超过 12 m³ 但不超过 18 m³ 的部分",
                          "6 元/m³"
                        ]
                      },
                      {
                        "id": "tier-3",
                        "cells": [
                          "超过 18 m³ 的部分",
                          "9 元/m³"
                        ]
                      }
                    ]
                  }
                ]
              },
              "solutionPath": "problems/senior-high/functions/function-representation/function-representation-20260727-q09.html",
              "groupId": "function-comprehensive",
              "groupLabel": "分段函数与综合应用"
            },
            {
              "id": "function-representation-20260727-q10",
              "number": 10,
              "source": "2026 江苏连云港期末",
              "problem": {
                "lines": [
                  {
                    "text": "已知函数 \\(f(x)=0\\)（\\(x<0\\)），\\(f(x)=1\\)（\\(x≥0\\)），则 \\(f(f(x))=\\)（　）　A. 0　B. 1　C. 2　D. 3",
                    "html": "已知函数 <span class=\"inline-math\">f(x)=0</span>（<span class=\"inline-math\">x&lt;0</span>），<span class=\"inline-math\">f(x)=1</span>（<span class=\"inline-math\">x≥0</span>），则 <span class=\"inline-math\">f(f(x))=</span>（　）　A. 0　B. 1　C. 2　D. 3"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-representation/function-representation-20260727-q10.html",
              "groupId": "function-comprehensive",
              "groupLabel": "分段函数与综合应用"
            },
            {
              "id": "function-representation-20260727-q11",
              "number": 11,
              "source": "2026 湖南长沙长郡中学期末",
              "problem": {
                "lines": [
                  {
                    "text": "已知函数 \\(f(x)=2x+1\\)（\\(x≥0\\)），\\(f(x)=3x^2\\)（\\(x<0\\)），且 \\(f(x_0)=3\\)，则实数 \\(x_0\\) 的值为______。",
                    "html": "已知函数 <span class=\"inline-math\">f(x)=2x+1</span>（<span class=\"inline-math\">x≥0</span>），<span class=\"inline-math\">f(x)=3x<sup>2</sup></span>（<span class=\"inline-math\">x&lt;0</span>），且 <span class=\"inline-math\">f(x<sub>0</sub>)=3</span>，则实数 <span class=\"inline-math\">x<sub>0</sub></span> 的值为______。"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-representation/function-representation-20260727-q11.html",
              "groupId": "function-comprehensive",
              "groupLabel": "分段函数与综合应用"
            },
            {
              "id": "function-representation-20260727-q12",
              "number": 12,
              "source": "2026 广东深圳期中",
              "problem": {
                "lines": [
                  {
                    "text": "已知函数 \\(f(x)=\\frac{1}{x}\\)（\\(-1≤x<0\\)），\\(f(x)=x^2-2x\\)（\\(0≤x≤3\\)），\\(f(x)=-2x+9\\)（\\(3<x≤4\\)）。",
                    "html": "已知函数 <span class=\"inline-math\">f(x)=<span class=\"math-fraction\"><span class=\"math-numerator\">1</span><span class=\"math-denominator\">x</span></span></span>（<span class=\"inline-math\">-1≤x&lt;0</span>），<span class=\"inline-math\">f(x)=x<sup>2</sup>-2x</span>（<span class=\"inline-math\">0≤x≤3</span>），<span class=\"inline-math\">f(x)=-2x+9</span>（<span class=\"inline-math\">3&lt;x≤4</span>）。"
                  },
                  {
                    "text": "（1）求 \\(f(4)\\)、\\(f(f(1))\\) 的值；",
                    "html": "（1）求 <span class=\"inline-math\">f(4)</span>、<span class=\"inline-math\">f(f(1))</span> 的值；"
                  },
                  {
                    "text": "（2）若 \\(f(a)=1\\)，求 a 的值；",
                    "html": "（2）若 <span class=\"inline-math\">f(a)=1</span>，求 a 的值；"
                  },
                  {
                    "text": "（3）在给定的坐标系中画出此函数的图象，并根据图象写出函数 \\(f(x)\\) 的值域。",
                    "html": "（3）在给定的坐标系中画出此函数的图象，并根据图象写出函数 <span class=\"inline-math\">f(x)</span> 的值域。"
                  },
                  {
                    "ariaLabel": "题目给定的空白坐标系",
                    "figures": [
                      {
                        "id": "blank-grid",
                        "title": "",
                        "ariaLabel": "横轴从负 3 到 4、纵轴从负 3 到 4 的坐标系",
                        "caption": ""
                      }
                    ]
                  },
                  {
                    "text": "写出各问结果。",
                    "html": "写出各问结果。"
                  }
                ]
              },
              "originalFigures": [
                {
                  "id": "blank-grid",
                  "renderId": "function-representation-20260727-q12--blank-grid",
                  "kind": "relationPlot"
                }
              ],
              "figureSpec": {
                "$schema": "../../schemas/function-spec.schema.json",
                "version": 1,
                "id": "function-representation-20260727-q12",
                "parameter": {
                  "name": "x",
                  "initial": 2
                },
                "panels": [
                  {
                    "id": "function-representation-20260727-q12--blank-grid",
                    "kind": "relationPlot",
                    "title": "题目给定坐标系",
                    "viewport": {
                      "x": 0.06,
                      "y": 0.06,
                      "width": 0.88,
                      "height": 0.88
                    },
                    "domain": {
                      "minX": -3,
                      "maxX": 4,
                      "minY": -3,
                      "maxY": 4
                    },
                    "axisPadding": {
                      "minX": 0.1,
                      "maxX": 0.1,
                      "minY": 0.1,
                      "maxY": 0.1
                    },
                    "segments": []
                  }
                ]
              },
              "solutionPath": "problems/senior-high/functions/function-representation/function-representation-20260727-q12.html",
              "groupId": "function-comprehensive",
              "groupLabel": "分段函数与综合应用"
            },
            {
              "id": "function-representation-20260727-q13",
              "number": 13,
              "problem": {
                "lines": [
                  {
                    "text": "某小组 4 位同学准备乘坐出租车去参加社会实践活动。已知全程 30 km，出租车收费标准为：起步价 11 元（乘车不超过 3 km）；行驶 3 km 后，每千米车费 2.2 元；行驶 10 km 后，每千米车费 2.8 元。",
                    "html": "某小组 4 位同学准备乘坐出租车去参加社会实践活动。已知全程 30 km，出租车收费标准为：起步价 11 元（乘车不超过 3 km）；行驶 3 km 后，每千米车费 2.2 元；行驶 10 km 后，每千米车费 2.8 元。"
                  },
                  {
                    "text": "（1）写出同学们乘车的费用 \\(f(x)\\)（单位：元）与路程 x（单位：km）的函数关系式；",
                    "html": "（1）写出同学们乘车的费用 <span class=\"inline-math\">f(x)</span>（单位：元）与路程 x（单位：km）的函数关系式；"
                  },
                  {
                    "text": "（2）比较三种方案：①一辆车行驶 30 km；②行驶 15 km 后换车，再行驶 15 km；③每行驶 10 km 后换车一次。哪一种方案最省钱？",
                    "html": "（2）比较三种方案：①一辆车行驶 30 km；②行驶 15 km 后换车，再行驶 15 km；③每行驶 10 km 后换车一次。哪一种方案最省钱？"
                  }
                ]
              },
              "originalFigures": [],
              "figureSpec": null,
              "solutionPath": "problems/senior-high/functions/function-representation/function-representation-20260727-q13.html",
              "groupId": "function-comprehensive",
              "groupLabel": "分段函数与综合应用"
            }
          ]
        }
      ]
    }
  ],
  "learningTopics": [
    {
      "id": "set-concepts-and-representation",
      "chapterId": "sets",
      "sectionId": "set-concepts-and-representation",
      "title": "集合的概念和表示",
      "eyebrow": "第一讲",
      "introduction": [
        "数学常用简洁的符号表达一类确定的研究对象。把符合共同条件的对象归在一起，就得到集合；其中的每一个对象称为元素。",
        "这一专题先认识集合与元素，再学习元素和集合的关系以及集合的表示方法，最后通过综合练习检验能否在不同情境中正确使用这些概念。"
      ],
      "introductionHtml": [
        "数学常用简洁的符号表达一类确定的研究对象。把符合共同条件的对象归在一起，就得到集合；其中的每一个对象称为元素。",
        "这一专题先认识集合与元素，再学习元素和集合的关系以及集合的表示方法，最后通过综合练习检验能否在不同情境中正确使用这些概念。"
      ],
      "mapNodes": [
        {
          "id": "set-concept",
          "label": "集合的概念",
          "moduleId": "set-concept",
          "children": [
            "集合",
            "空集",
            "元素",
            "确定性",
            "互异性",
            "无序性"
          ]
        },
        {
          "id": "element-set-relation",
          "label": "元素和集合的关系",
          "moduleId": "element-set-relation",
          "children": [
            "属于",
            "不属于"
          ]
        },
        {
          "id": "set-representation",
          "label": "集合的表示",
          "moduleId": "set-representation",
          "children": [
            "列举法",
            "描述法",
            "区间表示法",
            "Venn 图法"
          ]
        },
        {
          "id": "practice",
          "label": "实战练习",
          "moduleId": "practice",
          "children": [
            "概念辨析",
            "关系判断",
            "参数与表示"
          ]
        }
      ],
      "modules": [
        {
          "id": "set-concept",
          "label": "集合的概念",
          "type": "knowledge",
          "status": "published",
          "description": "认识集合、元素和空集，掌握集合中元素的三种基本性质。",
          "knowledgeGroups": [
            {
              "category": "concept",
              "number": "01",
              "eyebrow": "基本概念",
              "title": "集合的概念"
            },
            {
              "category": "property",
              "number": "02",
              "eyebrow": "元素性质",
              "title": "集合中元素的性质"
            }
          ],
          "knowledgeBlocks": [
            {
              "category": "concept",
              "title": "集合",
              "body": [
                "把一些元素组成的总体叫作集合，简称集。"
              ],
              "bodyHtml": [
                "把一些元素组成的总体叫作集合，简称集。"
              ]
            },
            {
              "category": "concept",
              "title": "元素",
              "body": [
                "一般地，把研究对象统称为元素。"
              ],
              "bodyHtml": [
                "一般地，把研究对象统称为元素。"
              ]
            },
            {
              "category": "concept",
              "title": "空集",
              "body": [
                "不含任何元素的集合叫作空集，记作 \\(\\varnothing\\)。"
              ],
              "bodyHtml": [
                "不含任何元素的集合叫作空集，记作 <span class=\"inline-math\">∅</span>。"
              ]
            },
            {
              "category": "property",
              "title": "确定性",
              "body": [
                "对于给定的集合和一个确定的对象，这个对象是否属于该集合必须能够明确判断。"
              ],
              "bodyHtml": [
                "对于给定的集合和一个确定的对象，这个对象是否属于该集合必须能够明确判断。"
              ]
            },
            {
              "category": "property",
              "title": "互异性",
              "body": [
                "一个集合中的元素互不相同；相同对象重复出现时只能算作一个元素。"
              ],
              "bodyHtml": [
                "一个集合中的元素互不相同；相同对象重复出现时只能算作一个元素。"
              ]
            },
            {
              "category": "property",
              "title": "无序性",
              "body": [
                "集合中的元素没有先后顺序。只要元素完全相同，排列顺序不同仍表示同一个集合。"
              ],
              "bodyHtml": [
                "集合中的元素没有先后顺序。只要元素完全相同，排列顺序不同仍表示同一个集合。"
              ]
            }
          ],
          "examples": [
            {
              "group": "确定性",
              "title": "集合中元素的确定性",
              "numberLabel": "",
              "display": "featured",
              "hints": [
                "判断每个对象是否有明确、统一的归属标准。",
                "注意“较好”“长寿”“近似”等描述是否给出了确定界限。"
              ],
              "answerSchema": {
                "type": "single-choice",
                "expected": "D"
              },
              "lesson": {
                "id": "set-concept-example-q01",
                "title": "集合的确定性：判断对象能否构成集合",
                "problem": {
                  "lines": [
                    {
                      "text": "下面给出的四类对象中，构成集合的是：",
                      "html": "下面给出的四类对象中，构成集合的是："
                    },
                    {
                      "text": "A. 某班视力较好的同学　　B. 长寿的人　　C. \\(\\pi\\) 的近似值　　D. 倒数等于它本身的数",
                      "html": "A. 某班视力较好的同学　　B. 长寿的人　　C. <span class=\"inline-math\">π</span> 的近似值　　D. 倒数等于它本身的数"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-concept-example-q01.html"
              }
            },
            {
              "group": "互异性",
              "title": "集合中元素的互异性",
              "numberLabel": "",
              "display": "featured",
              "hints": [
                "集合含有三个元素，意味着三个代数式必须两两不相等。",
                "分别找出会使任意两个代数式相等的参数值，再全部排除。"
              ],
              "answerSchema": {
                "type": "variable-domain",
                "variable": "x",
                "domain": "R",
                "expected": {
                  "excludedValues": [
                    "-1",
                    "1/4",
                    "2/3"
                  ]
                },
                "input": {
                  "mode": "math-expression",
                  "placeholder": "写出 x 满足的条件",
                  "keyboard": [
                    "x",
                    "real",
                    "in",
                    "not-in",
                    "not-equals",
                    "set-braces",
                    "set-minus",
                    "comma",
                    "digits",
                    "negative",
                    "fraction"
                  ]
                }
              },
              "lesson": {
                "id": "set-concept-example-q02",
                "title": "集合的互异性：求参数限制",
                "problem": {
                  "lines": [
                    {
                      "text": "已知集合 \\(A\\) 中含有三个元素：\\(3,2-x,3x+1\\)，求实数 \\(x\\) 应满足的条件。",
                      "html": "已知集合 <span class=\"inline-math\">A</span> 中含有三个元素：<span class=\"inline-math\">3,2-x,3x+1</span>，求实数 <span class=\"inline-math\">x</span> 应满足的条件。"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-concept-example-q02.html"
              }
            },
            {
              "group": "互异性",
              "title": "根集中的元素个数",
              "numberLabel": "",
              "display": "featured",
              "hints": [
                "先确认参数取不同值时，方程是否始终是二次方程。",
                "分别考虑退化为一次方程以及判别式大于、等于、小于零的情形。"
              ],
              "answerSchema": {
                "type": "finite-set-values",
                "expected": [
                  "0",
                  "1",
                  "2"
                ],
                "input": {
                  "mode": "math-expression",
                  "placeholder": "写出所有可能的元素个数",
                  "keyboard": [
                    "digits",
                    "set-braces",
                    "comma"
                  ]
                }
              },
              "lesson": {
                "id": "set-concept-example-q03",
                "title": "方程根集可能含有几个元素",
                "problem": {
                  "lines": [
                    {
                      "text": "已知方程 \\(ax^2-2x+1=0\\)，由方程的实根构成的集合中，可能有几个元素？",
                      "html": "已知方程 <span class=\"inline-math\">ax<sup>2</sup>-2x+1=0</span>，由方程的实根构成的集合中，可能有几个元素？"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-concept-example-q03.html"
              }
            },
            {
              "group": "互异性",
              "title": "集合元素的化简与去重",
              "numberLabel": "",
              "display": "featured",
              "hints": [
                "先化简绝对值、平方根和立方根，再判断实际出现了几种不同的数。",
                "分别考虑正数、负数和零，寻找能够达到的最大元素个数。"
              ],
              "answerSchema": {
                "type": "integer",
                "label": "最多有",
                "suffix": "个元素",
                "expected": "2",
                "input": {
                  "mode": "math-expression",
                  "placeholder": "填写答案",
                  "keyboard": [
                    "digits"
                  ]
                }
              },
              "lesson": {
                "id": "set-concept-example-q04",
                "title": "集合元素的化简与去重",
                "problem": {
                  "lines": [
                    {
                      "text": "由实数 \\(a,-a,|a|,\\sqrt{a^2},\\sqrt[3]{a^3}\\) 组成的集合，最多有几个元素？",
                      "html": "由实数 <span class=\"inline-math\">a,-a,|a|,<span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">a<sup>2</sup></span></span>,<span class=\"math-radical\"><span class=\"math-radical-symbol\">∛</span><span class=\"math-radicand\">a<sup>3</sup></span></span></span> 组成的集合，最多有几个元素？"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-concept-example-q04.html"
              }
            }
          ],
          "summary": "集合的定义涉及元素和集合两个基本概念。处理集合问题时，确定性帮助判断对象能否组成集合，互异性要求化简并去重，无序性说明元素的排列不会改变集合。",
          "summaryHtml": "集合的定义涉及元素和集合两个基本概念。处理集合问题时，确定性帮助判断对象能否组成集合，互异性要求化简并去重，无序性说明元素的排列不会改变集合。"
        },
        {
          "id": "element-set-relation",
          "label": "元素和集合的关系",
          "type": "knowledge",
          "status": "published",
          "description": "掌握属于与不属于的含义和符号，熟悉常用数集及其记号。",
          "knowledgeGroups": [
            {
              "category": "concept",
              "number": "01",
              "eyebrow": "关系符号",
              "title": "属于与不属于"
            },
            {
              "category": "property",
              "number": "02",
              "eyebrow": "常用数集",
              "title": "数集及其符号"
            }
          ],
          "knowledgeBlocks": [
            {
              "category": "concept",
              "title": "集合与元素的字母",
              "body": [
                "一般用英文大写字母 \\(A,B,C,\\ldots\\) 表示集合，用英文小写字母 \\(a,b,c,\\ldots\\) 表示元素。"
              ],
              "bodyHtml": [
                "一般用英文大写字母 <span class=\"inline-math\">A,B,C,…</span> 表示集合，用英文小写字母 <span class=\"inline-math\">a,b,c,…</span> 表示元素。"
              ]
            },
            {
              "category": "concept",
              "title": "属于",
              "body": [
                "如果 \\(a\\) 是集合 \\(A\\) 中的元素，就说 \\(a\\) 属于 \\(A\\)，记作 \\(a\\in A\\)。"
              ],
              "bodyHtml": [
                "如果 <span class=\"inline-math\">a</span> 是集合 <span class=\"inline-math\">A</span> 中的元素，就说 <span class=\"inline-math\">a</span> 属于 <span class=\"inline-math\">A</span>，记作 <span class=\"inline-math\">a∈ A</span>。"
              ]
            },
            {
              "category": "concept",
              "title": "不属于",
              "body": [
                "如果 \\(a\\) 不是集合 \\(A\\) 中的元素，就说 \\(a\\) 不属于 \\(A\\)，记作 \\(a\\notin A\\)。"
              ],
              "bodyHtml": [
                "如果 <span class=\"inline-math\">a</span> 不是集合 <span class=\"inline-math\">A</span> 中的元素，就说 <span class=\"inline-math\">a</span> 不属于 <span class=\"inline-math\">A</span>，记作 <span class=\"inline-math\">a<span class=\"math-notin\" role=\"img\" aria-label=\"不属于\"><svg viewBox=\"0 0 18 18\" aria-hidden=\"true\" focusable=\"false\"><path d=\"M15 3H9C5.3 3 3 5.5 3 9s2.3 6 6 6h6M3.7 9h10.8M4.5 16L14 2\"/></svg></span> A</span>。"
              ]
            },
            {
              "category": "property",
              "title": "自然数集",
              "body": [
                "记作 \\(\\mathbb N\\)，即 \\(\\{0,1,2,3,\\ldots\\}\\)。"
              ],
              "bodyHtml": [
                "记作 <span class=\"inline-math\"><span class=\"math-blackboard\">ℕ</span></span>，即 <span class=\"inline-math\">{0,1,2,3,…}</span>。"
              ]
            },
            {
              "category": "property",
              "title": "正整数集",
              "body": [
                "记作 \\(\\mathbb N^*\\)，即 \\(\\{1,2,3,\\ldots\\}\\)。"
              ],
              "bodyHtml": [
                "记作 <span class=\"inline-math\"><span class=\"math-blackboard\">ℕ</span><sup>*</sup></span>，即 <span class=\"inline-math\">{1,2,3,…}</span>。"
              ]
            },
            {
              "category": "property",
              "title": "整数集",
              "body": [
                "记作 \\(\\mathbb Z\\)。"
              ],
              "bodyHtml": [
                "记作 <span class=\"inline-math\"><span class=\"math-blackboard\">ℤ</span></span>。"
              ]
            },
            {
              "category": "property",
              "title": "有理数集",
              "body": [
                "记作 \\(\\mathbb Q\\)。"
              ],
              "bodyHtml": [
                "记作 <span class=\"inline-math\"><span class=\"math-blackboard\">ℚ</span></span>。"
              ]
            },
            {
              "category": "property",
              "title": "实数集",
              "body": [
                "记作 \\(\\mathbb R\\)。"
              ],
              "bodyHtml": [
                "记作 <span class=\"inline-math\"><span class=\"math-blackboard\">ℝ</span></span>。"
              ]
            }
          ],
          "examples": [
            {
              "group": "属于与不属于",
              "title": "用符号表示元素与集合的关系",
              "numberLabel": "",
              "display": "featured",
              "hints": [
                "先化简绝对值、分数或根式，再判断所得数属于哪个数集。",
                "属于用 \\(\\in\\)，不属于用 \\(\\notin\\)。"
              ],
              "answerSchema": {
                "type": "relation-sequence",
                "expected": [
                  "∉",
                  "∈",
                  "∉",
                  "∈",
                  "∉",
                  "∈",
                  "∈"
                ],
                "input": {
                  "mode": "math-expression",
                  "placeholder": "依次写出七个关系符号",
                  "keyboard": [
                    "in",
                    "not-in",
                    "comma"
                  ]
                }
              },
              "lesson": {
                "id": "set-element-relation-example-q01",
                "title": "用符号表示元素与集合的关系",
                "problem": {
                  "lines": [
                    {
                      "text": "用合适的符号表示下列元素与集合的关系：",
                      "html": "用合适的符号表示下列元素与集合的关系："
                    },
                    {
                      "text": "① \\(-1\\) ___ \\(\\mathbb N\\)；② \\(|-3|\\) ___ \\(\\mathbb N^*\\)；③ \\(\\frac12\\) ___ \\(\\mathbb Z\\)；④ \\(3.14\\) ___ \\(\\mathbb Q\\)；⑤ \\(\\sqrt5\\) ___ \\(\\mathbb Q\\)；⑥ \\(-\\frac{\\sqrt2}{2}\\) ___ \\(\\mathbb R\\)；⑦ \\(\\pi\\) ___ \\(\\mathbb R\\)。",
                      "html": "① <span class=\"inline-math\">-1</span> ___ <span class=\"inline-math\"><span class=\"math-blackboard\">ℕ</span></span>；② <span class=\"inline-math\">|-3|</span> ___ <span class=\"inline-math\"><span class=\"math-blackboard\">ℕ</span><sup>*</sup></span>；③ <span class=\"inline-math\"><span class=\"math-fraction\"><span class=\"math-numerator\">1</span><span class=\"math-denominator\">2</span></span></span> ___ <span class=\"inline-math\"><span class=\"math-blackboard\">ℤ</span></span>；④ <span class=\"inline-math\">3.14</span> ___ <span class=\"inline-math\"><span class=\"math-blackboard\">ℚ</span></span>；⑤ <span class=\"inline-math\"><span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">5</span></span></span> ___ <span class=\"inline-math\"><span class=\"math-blackboard\">ℚ</span></span>；⑥ <span class=\"inline-math\">-<span class=\"math-fraction\"><span class=\"math-numerator\"><span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">2</span></span></span><span class=\"math-denominator\">2</span></span></span> ___ <span class=\"inline-math\"><span class=\"math-blackboard\">ℝ</span></span>；⑦ <span class=\"inline-math\">π</span> ___ <span class=\"inline-math\"><span class=\"math-blackboard\">ℝ</span></span>。"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-element-relation-example-q01.html"
              }
            },
            {
              "group": "关系判断",
              "title": "判断关于常用数集的命题",
              "numberLabel": "",
              "display": "featured",
              "hints": [
                "整数的相反数仍是整数，但自然数的相反数不一定是自然数。",
                "检查涉及自然数的命题时，不要漏掉 \\(a=0\\)。"
              ],
              "answerSchema": {
                "type": "single-choice",
                "expected": "C"
              },
              "lesson": {
                "id": "set-element-relation-example-q02",
                "title": "判断关于常用数集的命题",
                "problem": {
                  "lines": [
                    {
                      "text": "下列叙述中正确的个数是：① 若 \\(-a\\in\\mathbb Z\\)，则 \\(a\\in\\mathbb Z\\)；② 若 \\(-a\\in\\mathbb N\\)，则 \\(a\\in\\mathbb N\\)；③ \\(a\\in\\mathbb Z\\)，若 \\(-a\\notin\\mathbb N\\)，则 \\(a\\in\\mathbb N\\)；④ \\(a\\in\\mathbb Z\\)，若 \\(a\\in\\mathbb N\\)，则 \\(-a\\notin\\mathbb N\\)。",
                      "html": "下列叙述中正确的个数是：① 若 <span class=\"inline-math\">-a∈<span class=\"math-blackboard\">ℤ</span></span>，则 <span class=\"inline-math\">a∈<span class=\"math-blackboard\">ℤ</span></span>；② 若 <span class=\"inline-math\">-a∈<span class=\"math-blackboard\">ℕ</span></span>，则 <span class=\"inline-math\">a∈<span class=\"math-blackboard\">ℕ</span></span>；③ <span class=\"inline-math\">a∈<span class=\"math-blackboard\">ℤ</span></span>，若 <span class=\"inline-math\">-a<span class=\"math-notin\" role=\"img\" aria-label=\"不属于\"><svg viewBox=\"0 0 18 18\" aria-hidden=\"true\" focusable=\"false\"><path d=\"M15 3H9C5.3 3 3 5.5 3 9s2.3 6 6 6h6M3.7 9h10.8M4.5 16L14 2\"/></svg></span><span class=\"math-blackboard\">ℕ</span></span>，则 <span class=\"inline-math\">a∈<span class=\"math-blackboard\">ℕ</span></span>；④ <span class=\"inline-math\">a∈<span class=\"math-blackboard\">ℤ</span></span>，若 <span class=\"inline-math\">a∈<span class=\"math-blackboard\">ℕ</span></span>，则 <span class=\"inline-math\">-a<span class=\"math-notin\" role=\"img\" aria-label=\"不属于\"><svg viewBox=\"0 0 18 18\" aria-hidden=\"true\" focusable=\"false\"><path d=\"M15 3H9C5.3 3 3 5.5 3 9s2.3 6 6 6h6M3.7 9h10.8M4.5 16L14 2\"/></svg></span><span class=\"math-blackboard\">ℕ</span></span>。"
                    },
                    {
                      "text": "A. 0 个　　B. 1 个　　C. 2 个　　D. 3 个",
                      "html": "A. 0 个　　B. 1 个　　C. 2 个　　D. 3 个"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-element-relation-example-q02.html"
              }
            }
          ],
          "summary": "元素与集合之间只有属于和不属于两种关系，分别记作 \\(\\in\\) 和 \\(\\notin\\)。判断时要先化简元素，并准确掌握 \\(\\mathbb N\\)、\\(\\mathbb N^*\\)、\\(\\mathbb Z\\)、\\(\\mathbb Q\\)、\\(\\mathbb R\\) 所表示的数集。",
          "summaryHtml": "元素与集合之间只有属于和不属于两种关系，分别记作 <span class=\"inline-math\">∈</span> 和 <span class=\"inline-math\"><span class=\"math-notin\" role=\"img\" aria-label=\"不属于\"><svg viewBox=\"0 0 18 18\" aria-hidden=\"true\" focusable=\"false\"><path d=\"M15 3H9C5.3 3 3 5.5 3 9s2.3 6 6 6h6M3.7 9h10.8M4.5 16L14 2\"/></svg></span></span>。判断时要先化简元素，并准确掌握 <span class=\"inline-math\"><span class=\"math-blackboard\">ℕ</span></span>、<span class=\"inline-math\"><span class=\"math-blackboard\">ℕ</span><sup>*</sup></span>、<span class=\"inline-math\"><span class=\"math-blackboard\">ℤ</span></span>、<span class=\"inline-math\"><span class=\"math-blackboard\">ℚ</span></span>、<span class=\"inline-math\"><span class=\"math-blackboard\">ℝ</span></span> 所表示的数集。"
        },
        {
          "id": "set-representation",
          "label": "集合的表示",
          "type": "knowledge",
          "status": "published",
          "description": "掌握列举法、描述法、区间表示法和 Venn 图法，并能根据对象特点选择合适的表示方式。",
          "knowledgeGroups": [
            {
              "category": "enumeration",
              "number": "01",
              "eyebrow": "逐一写出",
              "title": "列举法"
            },
            {
              "category": "description",
              "number": "02",
              "eyebrow": "共同特征",
              "title": "描述法"
            },
            {
              "category": "interval",
              "number": "03",
              "eyebrow": "连续数集",
              "title": "区间表示法"
            },
            {
              "category": "venn",
              "number": "04",
              "eyebrow": "图形表达",
              "title": "Venn 图法",
              "visual": "venn-classification"
            }
          ],
          "knowledgeBlocks": [
            {
              "category": "enumeration",
              "title": "列举法",
              "body": [
                "把集合的所有元素一一列举出来，并用花括号“{ }”括起来。",
                "列举时必须做到不遗漏、不重复；集合中的元素没有先后顺序。"
              ],
              "bodyHtml": [
                "把集合的所有元素一一列举出来，并用花括号“{ }”括起来。",
                "列举时必须做到不遗漏、不重复；集合中的元素没有先后顺序。"
              ]
            },
            {
              "category": "description",
              "title": "描述法",
              "body": [
                "设 \\(A\\) 是一个集合，把集合中具有共同特征 \\(P(x)\\) 的元素写成 \\(\\{x\\in A\\mid P(x)\\}\\)。",
                "竖线左侧是代表元素及其范围，右侧是元素必须满足的共同特征。"
              ],
              "bodyHtml": [
                "设 <span class=\"inline-math\">A</span> 是一个集合，把集合中具有共同特征 <span class=\"inline-math\">P(x)</span> 的元素写成 <span class=\"inline-math\">{x∈ A| P(x)}</span>。",
                "竖线左侧是代表元素及其范围，右侧是元素必须满足的共同特征。"
              ]
            },
            {
              "category": "interval",
              "title": "有限区间",
              "body": [
                "\\([a,b]\\)、\\((a,b)\\)、\\([a,b)\\)、\\((a,b]\\) 分别表示闭区间、开区间、左闭右开区间和左开右闭区间。",
                "方括号表示端点属于集合，圆括号表示端点不属于集合。"
              ],
              "bodyHtml": [
                "<span class=\"inline-math\">[a,b]</span>、<span class=\"inline-math\">(a,b)</span>、<span class=\"inline-math\">[a,b)</span>、<span class=\"inline-math\">(a,b]</span> 分别表示闭区间、开区间、左闭右开区间和左开右闭区间。",
                "方括号表示端点属于集合，圆括号表示端点不属于集合。"
              ]
            },
            {
              "category": "interval",
              "title": "无穷区间",
              "body": [
                "\\([a,+∞)\\)、\\((a,+∞)\\)、\\((-∞,a]\\)、\\((-∞,a)\\) 用于表示一端无限延伸的实数集合。",
                "正、负无穷不是实数，因此无穷端一律使用圆括号。"
              ],
              "bodyHtml": [
                "<span class=\"inline-math\">[a,+∞)</span>、<span class=\"inline-math\">(a,+∞)</span>、<span class=\"inline-math\">(-∞,a]</span>、<span class=\"inline-math\">(-∞,a)</span> 用于表示一端无限延伸的实数集合。",
                "正、负无穷不是实数，因此无穷端一律使用圆括号。"
              ]
            },
            {
              "category": "venn",
              "title": "Venn 图",
              "body": [
                "用平面内一条封闭曲线的内部表示一个集合，曲线的位置关系直观反映集合之间的关系。",
                "曲线嵌套表示集合间的包含关系，曲线相交表示两个集合存在公共元素。"
              ],
              "bodyHtml": [
                "用平面内一条封闭曲线的内部表示一个集合，曲线的位置关系直观反映集合之间的关系。",
                "曲线嵌套表示集合间的包含关系，曲线相交表示两个集合存在公共元素。"
              ]
            }
          ],
          "examples": [
            {
              "group": "列举法",
              "title": "列举指定范围内的整数",
              "numberLabel": "练习 4 · 1",
              "display": "featured",
              "hints": [
                "先确定范围内有哪些整数。",
                "使用花括号并用逗号分隔元素。"
              ],
              "answerSchema": {
                "type": "finite-set-values",
                "expected": [
                  "2",
                  "3",
                  "4",
                  "5"
                ],
                "input": {
                  "mode": "math-expression",
                  "placeholder": "写出集合",
                  "keyboard": [
                    "set-braces",
                    "comma",
                    "digits"
                  ]
                }
              },
              "lesson": {
                "id": "set-representation-enumeration-q01",
                "title": "列举指定范围内的整数",
                "problem": {
                  "lines": [
                    {
                      "text": "用列举法表示大于 1 且小于 6 的整数所组成的集合。",
                      "html": "用列举法表示大于 1 且小于 6 的整数所组成的集合。"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-representation-enumeration-q01.html"
              }
            },
            {
              "group": "列举法",
              "title": "用解集表示方程组的解",
              "numberLabel": "练习 4 · 2",
              "display": "featured",
              "hints": [
                "方程组的解是有序数对。"
              ],
              "answerSchema": {
                "type": "single-choice",
                "expected": "B"
              },
              "lesson": {
                "id": "set-representation-enumeration-q02",
                "title": "用解集表示方程组的解",
                "problem": {
                  "lines": [
                    {
                      "text": "方程组 \\(x+y=4，x-y=2\\) 的解集为（　）。",
                      "html": "方程组 <span class=\"inline-math\">x+y=4，x-y=2</span> 的解集为（　）。"
                    },
                    {
                      "text": "A. \\(\\{3,1\\}\\)　B. \\(\\{(3,1)\\}\\)　C. \\((3,1)\\)　D. \\(\\{(1,3)\\}\\)",
                      "html": "A. <span class=\"inline-math\">{3,1}</span>　B. <span class=\"inline-math\">{(3,1)}</span>　C. <span class=\"inline-math\">(3,1)</span>　D. <span class=\"inline-math\">{(1,3)}</span>"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-representation-enumeration-q02.html"
              }
            },
            {
              "group": "列举法",
              "title": "辨认方程组解集的正确写法",
              "numberLabel": "练习 4 · 3",
              "display": "featured",
              "hints": [
                "注意有序数对外还需要集合的花括号。"
              ],
              "answerSchema": {
                "type": "single-choice",
                "choiceStyle": "ordinal",
                "expected": "③"
              },
              "lesson": {
                "id": "set-representation-enumeration-q03",
                "title": "辨认方程组解集的正确写法",
                "problem": {
                  "lines": [
                    {
                      "text": "方程组 \\(x+y=3，x-y=1\\) 的解集是：① \\(\\{2,1\\}\\)；② \\(\\{x=2,y=1\\}\\)；③ \\(\\{(2,1)\\}\\)；④ \\(\\{(1,2)\\}\\)。",
                      "html": "方程组 <span class=\"inline-math\">x+y=3，x-y=1</span> 的解集是：① <span class=\"inline-math\">{2,1}</span>；② <span class=\"inline-math\">{x=2,y=1}</span>；③ <span class=\"inline-math\">{(2,1)}</span>；④ <span class=\"inline-math\">{(1,2)}</span>。"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-representation-enumeration-q03.html"
              }
            },
            {
              "group": "列举法",
              "title": "由元素属于集合求参数",
              "numberLabel": "练习 4 · 4",
              "display": "featured",
              "hints": [
                "分类得到候选值后检查互异性。"
              ],
              "answerSchema": {
                "type": "exact-expression",
                "expected": [
                  "-3/2"
                ],
                "input": {
                  "mode": "math-expression",
                  "placeholder": "填写 a",
                  "keyboard": [
                    "negative",
                    "digits",
                    "fraction"
                  ]
                }
              },
              "lesson": {
                "id": "set-representation-enumeration-q04",
                "title": "由元素属于集合求参数",
                "problem": {
                  "lines": [
                    {
                      "text": "设集合 \\(A=\\{2,a+2,2a^2+a\\}\\)，若 \\(3\\in A\\)，求 \\(a\\)。",
                      "html": "设集合 <span class=\"inline-math\">A={2,a+2,2a<sup>2</sup>+a}</span>，若 <span class=\"inline-math\">3∈ A</span>，求 <span class=\"inline-math\">a</span>。"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-representation-enumeration-q04.html"
              }
            },
            {
              "group": "列举法",
              "title": "检查集合中的参数候选值",
              "numberLabel": "练习 4 · 5",
              "display": "featured",
              "hints": [
                "得到候选值后，还要检查集合中三个元素的互异性。"
              ],
              "answerSchema": {
                "type": "single-choice",
                "expected": "C"
              },
              "lesson": {
                "id": "set-representation-enumeration-q05",
                "title": "检查集合中的参数候选值",
                "problem": {
                  "lines": [
                    {
                      "text": "已知集合 \\(A=\\{0,m,m^2-2m+3\\}\\)，且 \\(3\\in A\\)，则实数 \\(m\\) 为（　）。",
                      "html": "已知集合 <span class=\"inline-math\">A={0,m,m<sup>2</sup>-2m+3}</span>，且 <span class=\"inline-math\">3∈ A</span>，则实数 <span class=\"inline-math\">m</span> 为（　）。"
                    },
                    {
                      "text": "A. \\(2\\)　B. \\(3\\)　C. \\(2\\) 或 \\(3\\)　D. \\(0\\) 或 \\(2\\) 或 \\(3\\)",
                      "html": "A. <span class=\"inline-math\">2</span>　B. <span class=\"inline-math\">3</span>　C. <span class=\"inline-math\">2</span> 或 <span class=\"inline-math\">3</span>　D. <span class=\"inline-math\">0</span> 或 <span class=\"inline-math\">2</span> 或 <span class=\"inline-math\">3</span>"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-representation-enumeration-q05.html"
              }
            },
            {
              "group": "列举法",
              "title": "利用两个列举集合相等求值",
              "numberLabel": "练习 4 · 6",
              "display": "featured",
              "hints": [
                "先利用零元素确定 b。"
              ],
              "answerSchema": {
                "type": "integer",
                "expected": "-1",
                "input": {
                  "mode": "math-expression",
                  "placeholder": "填写答案",
                  "keyboard": [
                    "negative",
                    "digits"
                  ]
                }
              },
              "lesson": {
                "id": "set-representation-enumeration-q06",
                "title": "利用两个列举集合相等求值",
                "problem": {
                  "lines": [
                    {
                      "text": "含有 3 个实数的集合可表示为 \\(\\{a,\\frac{b}{a},1\\}\\)，又可表示为 \\(\\{a^2,a+b,0\\}\\)，求 \\(a^{2019}+b^{2019}\\)。",
                      "html": "含有 3 个实数的集合可表示为 <span class=\"inline-math\">{a,<span class=\"math-fraction\"><span class=\"math-numerator\">b</span><span class=\"math-denominator\">a</span></span>,1}</span>，又可表示为 <span class=\"inline-math\">{a<sup>2</sup>,a+b,0}</span>，求 <span class=\"inline-math\">a<sup>2019</sup>+b<sup>2019</sup></span>。"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-representation-enumeration-q06.html"
              }
            },
            {
              "group": "描述法",
              "title": "读懂描述法中代表元素的含义",
              "numberLabel": "练习 5 · 1",
              "display": "featured",
              "hints": [
                "先看竖线左侧的代表元素。"
              ],
              "answerSchema": {
                "type": "multipart-exact",
                "layout": "per-part",
                "expected": [
                  {
                    "label": "（1）",
                    "prompt": "\\(\\{x\\in\\mathbb R\\mid x<4\\}\\)",
                    "aliases": [
                      "(-∞,4)",
                      "小于4的全体实数",
                      "小于4的实数"
                    ],
                    "promptHtml": "<span class=\"inline-math\">{x∈<span class=\"math-blackboard\">ℝ</span>| x&lt;4}</span>"
                  },
                  {
                    "label": "（2）",
                    "prompt": "\\(\\{y\\in\\mathbb R\\mid y<4\\}\\)",
                    "aliases": [
                      "(-∞,4)",
                      "小于4的全体实数",
                      "小于4的实数"
                    ],
                    "promptHtml": "<span class=\"inline-math\">{y∈<span class=\"math-blackboard\">ℝ</span>| y&lt;4}</span>"
                  },
                  {
                    "label": "（3）",
                    "prompt": "\\(\\{y\\in\\mathbb N\\mid y<4\\}\\)",
                    "note": "ℕ 表示自然数集。",
                    "aliases": [
                      "{0,1,2,3}",
                      "小于4的自然数"
                    ],
                    "promptHtml": "<span class=\"inline-math\">{y∈<span class=\"math-blackboard\">ℕ</span>| y&lt;4}</span>"
                  },
                  {
                    "label": "（4）",
                    "prompt": "\\(\\{x\\mid y=x^2+1\\}\\)",
                    "aliases": [
                      "ℝ",
                      "R",
                      "全体实数"
                    ],
                    "promptHtml": "<span class=\"inline-math\">{x| y=x<sup>2</sup>+1}</span>"
                  },
                  {
                    "label": "（5）",
                    "prompt": "\\(\\{y\\mid y=x^2+1\\}\\)",
                    "aliases": [
                      "[1,∞)",
                      "大于等于1的全体实数",
                      "不小于1的全体实数"
                    ],
                    "promptHtml": "<span class=\"inline-math\">{y| y=x<sup>2</sup>+1}</span>"
                  },
                  {
                    "label": "（6）",
                    "prompt": "\\(\\{(x,y)\\mid y=x^2+1\\}\\)",
                    "aliases": [
                      "{(x,y)|y=x^2+1}",
                      "抛物线y=x^2+1上的所有点"
                    ],
                    "promptHtml": "<span class=\"inline-math\">{(x,y)| y=x<sup>2</sup>+1}</span>"
                  }
                ],
                "input": {
                  "mode": "text",
                  "placeholder": "用自然语言描述该集合"
                }
              },
              "lesson": {
                "id": "set-representation-description-q01",
                "title": "读懂描述法中代表元素的含义",
                "problem": {
                  "lines": [
                    {
                      "text": "试用自然语言叙述下列集合所包含的元素：",
                      "html": "试用自然语言叙述下列集合所包含的元素："
                    },
                    {
                      "text": "（1）\\(\\{x\\in\\mathbb R\\mid x<4\\}\\)；（2）\\(\\{y\\in\\mathbb R\\mid y<4\\}\\)；（3）\\(\\{y\\in\\mathbb N\\mid y<4\\}\\)；",
                      "html": "（1）<span class=\"inline-math\">{x∈<span class=\"math-blackboard\">ℝ</span>| x&lt;4}</span>；（2）<span class=\"inline-math\">{y∈<span class=\"math-blackboard\">ℝ</span>| y&lt;4}</span>；（3）<span class=\"inline-math\">{y∈<span class=\"math-blackboard\">ℕ</span>| y&lt;4}</span>；"
                    },
                    {
                      "text": "（4）\\(\\{x\\mid y=x^2+1\\}\\)；（5）\\(\\{y\\mid y=x^2+1\\}\\)；（6）\\(\\{(x,y)\\mid y=x^2+1\\}\\)。",
                      "html": "（4）<span class=\"inline-math\">{x| y=x<sup>2</sup>+1}</span>；（5）<span class=\"inline-math\">{y| y=x<sup>2</sup>+1}</span>；（6）<span class=\"inline-math\">{(x,y)| y=x<sup>2</sup>+1}</span>。"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-representation-description-q01.html"
              }
            },
            {
              "group": "描述法",
              "title": "把描述法集合改写为列举法",
              "numberLabel": "练习 6 · 1",
              "display": "featured",
              "hints": [
                "先解不等式，再与自然数集取交集。"
              ],
              "answerSchema": {
                "type": "finite-set-values",
                "expected": [
                  "0",
                  "1",
                  "2",
                  "3",
                  "4"
                ],
                "input": {
                  "mode": "math-expression",
                  "placeholder": "写出集合 A",
                  "keyboard": [
                    "set-braces",
                    "comma",
                    "digits"
                  ]
                }
              },
              "lesson": {
                "id": "set-representation-description-q02",
                "title": "把描述法集合改写为列举法",
                "source": "2023 南开中学第一次月考",
                "problem": {
                  "lines": [
                    {
                      "text": "用列举法表示集合 \\(A=\\{x\\mid 3x-1\\le11, x\\in\\mathbb N\\}\\)。",
                      "html": "用列举法表示集合 <span class=\"inline-math\">A={x| 3x-1≤11, x∈<span class=\"math-blackboard\">ℕ</span>}</span>。"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-representation-description-q02.html"
              }
            },
            {
              "group": "描述法",
              "title": "列举不等式中的整数解",
              "numberLabel": "练习 6 · 2",
              "display": "featured",
              "hints": [
                "解双边不等式后筛选整数。"
              ],
              "answerSchema": {
                "type": "exact-expression",
                "expected": [
                  "{0,1}",
                  "0,1"
                ],
                "input": {
                  "mode": "math-expression",
                  "placeholder": "写出集合",
                  "keyboard": [
                    "set-braces",
                    "comma",
                    "digits"
                  ]
                }
              },
              "lesson": {
                "id": "set-representation-description-q03",
                "title": "列举不等式中的整数解",
                "problem": {
                  "lines": [
                    {
                      "text": "集合 \\(\\{x\\in\\mathbb Z\\mid -3<2x-1<3\\}\\) 用列举法表示。",
                      "html": "集合 <span class=\"inline-math\">{x∈<span class=\"math-blackboard\">ℤ</span>| -3&lt;2x-1&lt;3}</span> 用列举法表示。"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-representation-description-q03.html"
              }
            },
            {
              "group": "描述法",
              "title": "列举含整除条件的集合",
              "numberLabel": "练习 6 · 3（1）",
              "display": "featured",
              "hints": [
                "把分母视作 6 的整数因数。"
              ],
              "answerSchema": {
                "type": "exact-expression",
                "expected": [
                  "{-4,-1,0,1,3,4,5,8}"
                ],
                "input": {
                  "mode": "math-expression",
                  "placeholder": "写出集合",
                  "keyboard": [
                    "set-braces",
                    "comma",
                    "negative",
                    "digits"
                  ]
                }
              },
              "lesson": {
                "id": "set-representation-description-q04",
                "title": "列举含整除条件的集合",
                "problem": {
                  "lines": [
                    {
                      "text": "用列举法表示集合 \\(\\{x\\mid \\frac{6}{2-x}\\in\\mathbb Z, x\\in\\mathbb Z\\}\\)。",
                      "html": "用列举法表示集合 <span class=\"inline-math\">{x| <span class=\"math-fraction\"><span class=\"math-numerator\">6</span><span class=\"math-denominator\">2-x</span></span>∈<span class=\"math-blackboard\">ℤ</span>, x∈<span class=\"math-blackboard\">ℤ</span>}</span>。"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-representation-description-q04.html"
              }
            },
            {
              "group": "描述法",
              "title": "列举有限范围内的有理数",
              "numberLabel": "练习 6 · 3（2）",
              "display": "featured",
              "hints": [
                "枚举 a、b 后对结果去重。"
              ],
              "answerSchema": {
                "type": "exact-expression",
                "expected": [
                  "{-1,-1/2,0,1/2,1}"
                ],
                "input": {
                  "mode": "math-expression",
                  "placeholder": "写出集合",
                  "keyboard": [
                    "set-braces",
                    "comma",
                    "negative",
                    "digits",
                    "fraction"
                  ]
                }
              },
              "lesson": {
                "id": "set-representation-description-q05",
                "title": "列举有限范围内的有理数",
                "problem": {
                  "lines": [
                    {
                      "text": "用列举法表示集合 \\(\\{x\\mid x=\\frac{a}{b}, a\\in\\mathbb Z, |a|<2, b\\in\\mathbb N^*, b<3\\}\\)。",
                      "html": "用列举法表示集合 <span class=\"inline-math\">{x| x=<span class=\"math-fraction\"><span class=\"math-numerator\">a</span><span class=\"math-denominator\">b</span></span>, a∈<span class=\"math-blackboard\">ℤ</span>, |a|&lt;2, b∈<span class=\"math-blackboard\">ℕ</span><sup>*</sup>, b&lt;3}</span>。"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-representation-description-q05.html"
              }
            },
            {
              "group": "描述法",
              "title": "列举满足条件的有序数对",
              "numberLabel": "练习 6 · 3（3）",
              "display": "featured",
              "hints": [
                "集合元素是有序数对。"
              ],
              "answerSchema": {
                "type": "exact-expression",
                "expected": [
                  "{(1,2),(2,4),(3,6)}"
                ],
                "input": {
                  "mode": "math-expression",
                  "placeholder": "写出集合",
                  "keyboard": [
                    "set-braces",
                    "interval",
                    "comma",
                    "digits"
                  ]
                }
              },
              "lesson": {
                "id": "set-representation-description-q06",
                "title": "列举满足条件的有序数对",
                "problem": {
                  "lines": [
                    {
                      "text": "用列举法表示集合 \\(\\{(x,y)\\mid y=2x, x\\in\\mathbb N, 1\\le x<4\\}\\)。",
                      "html": "用列举法表示集合 <span class=\"inline-math\">{(x,y)| y=2x, x∈<span class=\"math-blackboard\">ℕ</span>, 1≤ x&lt;4}</span>。"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-representation-description-q06.html"
              }
            },
            {
              "group": "描述法",
              "title": "辨析不同形式表示的集合",
              "numberLabel": "练习 7 · 1",
              "display": "featured",
              "hints": [
                "集合无序，但有序数对有顺序。"
              ],
              "answerSchema": {
                "type": "single-choice",
                "expected": "B"
              },
              "lesson": {
                "id": "set-representation-description-q07",
                "title": "辨析不同形式表示的集合",
                "problem": {
                  "lines": [
                    {
                      "text": "下列四组中表示同一集合的为（　）。",
                      "html": "下列四组中表示同一集合的为（　）。"
                    },
                    {
                      "text": "A. \\(M=\\{(-1,3)\\},N=\\{(3,-1)\\}\\)　B. \\(M=\\{-1,3\\},N=\\{3,-1\\}\\)　C. \\(M=\\{(x,y)\\mid y=x^2+3x\\},N=\\{x\\mid y=x^2+3x\\}\\)　D. \\(M=\\{0\\},N=0\\)",
                      "html": "A. <span class=\"inline-math\">M={(-1,3)},N={(3,-1)}</span>　B. <span class=\"inline-math\">M={-1,3},N={3,-1}</span>　C. <span class=\"inline-math\">M={(x,y)| y=x<sup>2</sup>+3x},N={x| y=x<sup>2</sup>+3x}</span>　D. <span class=\"inline-math\">M={0},N=0</span>"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-representation-description-q07.html"
              }
            },
            {
              "group": "描述法",
              "title": "由取值范围判断集合相等",
              "numberLabel": "练习 7 · 2",
              "display": "featured",
              "hints": [
                "比较代表元素的类型和范围。"
              ],
              "answerSchema": {
                "type": "single-choice",
                "expected": "D"
              },
              "lesson": {
                "id": "set-representation-description-q08",
                "title": "由取值范围判断集合相等",
                "problem": {
                  "lines": [
                    {
                      "text": "下列集合中表示同一集合的是（　）。",
                      "html": "下列集合中表示同一集合的是（　）。"
                    },
                    {
                      "text": "A. \\(M=\\{(3,2)\\},N=\\{(2,3)\\}\\)　B. \\(M=\\{(x,y)\\mid x+y=1\\},N=\\{y\\mid x+y=1\\}\\)　C. \\(M=\\{1,2\\},N=\\{(1,2)\\}\\)　D. \\(M=\\{y\\mid y=x^2+3\\},N=\\{x\\mid y=\\sqrt{x-3}\\}\\)",
                      "html": "A. <span class=\"inline-math\">M={(3,2)},N={(2,3)}</span>　B. <span class=\"inline-math\">M={(x,y)| x+y=1},N={y| x+y=1}</span>　C. <span class=\"inline-math\">M={1,2},N={(1,2)}</span>　D. <span class=\"inline-math\">M={y| y=x<sup>2</sup>+3},N={x| y=<span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">x-3</span></span>}</span>"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-representation-description-q08.html"
              }
            },
            {
              "group": "描述法",
              "title": "按乘积条件统计有序数对",
              "numberLabel": "练习 8 · 1",
              "display": "featured",
              "hints": [
                "集合不大时枚举所有情况；集合较大时先枚举部分情况，再找规律计数。"
              ],
              "answerSchema": {
                "type": "integer",
                "expected": "10",
                "input": {
                  "mode": "math-expression",
                  "placeholder": "填写个数",
                  "keyboard": [
                    "digits"
                  ]
                }
              },
              "lesson": {
                "id": "set-representation-description-q09",
                "title": "按乘积条件统计有序数对",
                "problem": {
                  "lines": [
                    {
                      "text": "已知 \\(A=\\{1,2,4,5,6\\}\\)，\\(B=\\{(x,y)\\mid x\\in A,y\\in A,xy\\in A\\}\\)，求集合 B 的元素个数。",
                      "html": "已知 <span class=\"inline-math\">A={1,2,4,5,6}</span>，<span class=\"inline-math\">B={(x,y)| x∈ A,y∈ A,xy∈ A}</span>，求集合 B 的元素个数。"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-representation-description-q09.html"
              }
            },
            {
              "group": "描述法",
              "title": "按新定义运算列举集合",
              "numberLabel": "练习 8 · 2",
              "display": "featured",
              "hints": [
                "枚举全部搭配并去重。"
              ],
              "answerSchema": {
                "type": "exact-expression",
                "expected": [
                  "{-3,-1,1,3}"
                ],
                "input": {
                  "mode": "math-expression",
                  "placeholder": "写出集合",
                  "keyboard": [
                    "set-braces",
                    "comma",
                    "negative",
                    "digits"
                  ]
                }
              },
              "lesson": {
                "id": "set-representation-description-q10",
                "title": "按新定义运算列举集合",
                "problem": {
                  "lines": [
                    {
                      "text": "若 \\(A=\\{1,2,3\\},B=\\{3,5\\}\\)，用列举法表示 \\(A*B=\\{2a-b\\mid a\\in A,b\\in B\\}\\)。",
                      "html": "若 <span class=\"inline-math\">A={1,2,3},B={3,5}</span>，用列举法表示 <span class=\"inline-math\">A*B={2a-b| a∈ A,b∈ B}</span>。"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-representation-description-q10.html"
              }
            },
            {
              "group": "描述法",
              "title": "按差值条件统计有序数对",
              "numberLabel": "练习 8 · 3",
              "display": "featured",
              "hints": [
                "条件等价于 x≥y。"
              ],
              "answerSchema": {
                "type": "integer",
                "expected": "10",
                "input": {
                  "mode": "math-expression",
                  "placeholder": "填写个数",
                  "keyboard": [
                    "digits"
                  ]
                }
              },
              "lesson": {
                "id": "set-representation-description-q11",
                "title": "按差值条件统计有序数对",
                "problem": {
                  "lines": [
                    {
                      "text": "若 \\(A=\\{0,1,2,3\\}\\)，\\(B=\\{(x,y)\\mid x\\in A,y\\in A,x-y\\in A\\}\\)，求 B 中元素的个数。",
                      "html": "若 <span class=\"inline-math\">A={0,1,2,3}</span>，<span class=\"inline-math\">B={(x,y)| x∈ A,y∈ A,x-y∈ A}</span>，求 B 中元素的个数。"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-representation-description-q11.html"
              }
            },
            {
              "group": "描述法",
              "title": "求差值封闭时有序数对的最大数量",
              "numberLabel": "练习 8 · 4",
              "display": "featured",
              "hints": [
                "正差要求 a>b。"
              ],
              "answerSchema": {
                "type": "integer",
                "expected": "190",
                "input": {
                  "mode": "math-expression",
                  "placeholder": "填写最大个数",
                  "keyboard": [
                    "digits"
                  ]
                }
              },
              "lesson": {
                "id": "set-representation-description-q12",
                "title": "求差值封闭时有序数对的最大数量",
                "problem": {
                  "lines": [
                    {
                      "text": "已知集合 \\(A=\\{a_1,a_2,\\ldots,a_{20}\\}\\)，且 \\(a_k>0\\)。集合 \\(B=\\{(a,b)\\mid a\\in A,b\\in A,a-b\\in A\\}\\)，求 B 中元素至多有多少个。",
                      "html": "已知集合 <span class=\"inline-math\">A={a<sub>1</sub>,a<sub>2</sub>,…,a<sub>20</sub>}</span>，且 <span class=\"inline-math\">a<sub>k</sub>&gt;0</span>。集合 <span class=\"inline-math\">B={(a,b)| a∈ A,b∈ A,a-b∈ A}</span>，求 B 中元素至多有多少个。"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-representation-description-q12.html"
              }
            },
            {
              "group": "描述法",
              "title": "计算新定义集合中元素之和",
              "numberLabel": "练习 8 · 5",
              "display": "featured",
              "hints": [
                "先去重，再求和。"
              ],
              "answerSchema": {
                "type": "single-choice",
                "expected": "A"
              },
              "lesson": {
                "id": "set-representation-description-q13",
                "title": "计算新定义集合中元素之和",
                "problem": {
                  "lines": [
                    {
                      "text": "定义 \\(A*B=\\{z\\mid z=x^2(y-1),x\\in A,y\\in B\\}\\)。若 \\(A=\\{-1,1\\},B=\\{0,2\\}\\)，求集合 A*B 中所有元素之和。",
                      "html": "定义 <span class=\"inline-math\">A*B={z| z=x<sup>2</sup>(y-1),x∈ A,y∈ B}</span>。若 <span class=\"inline-math\">A={-1,1},B={0,2}</span>，求集合 A*B 中所有元素之和。"
                    },
                    {
                      "text": "A. \\(0\\)　B. \\(1\\)　C. \\(2\\)　D. \\(3\\)",
                      "html": "A. <span class=\"inline-math\">0</span>　B. <span class=\"inline-math\">1</span>　C. <span class=\"inline-math\">2</span>　D. <span class=\"inline-math\">3</span>"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-representation-description-q13.html"
              }
            },
            {
              "group": "描述法",
              "title": "研究变换封闭的有限集合",
              "numberLabel": "练习 8 · 6",
              "display": "featured",
              "hints": [
                "连续施加三次变换会回到原数。"
              ],
              "answerSchema": {
                "type": "multipart-exact",
                "expected": [
                  {
                    "aliases": [
                      "{-1,1/2}",
                      "{1/2,-1}"
                    ]
                  },
                  {
                    "aliases": [
                      "否",
                      "不可能",
                      "no"
                    ]
                  },
                  {
                    "aliases": [
                      "{-1,-1/2,1/2,2/3,2,3}"
                    ]
                  }
                ],
                "input": {
                  "mode": "math-expression",
                  "placeholder": "按（1）至（3）顺序填写，用分号分隔",
                  "keyboard": [
                    "set-braces",
                    "comma",
                    "semicolon",
                    "negative",
                    "digits",
                    "fraction"
                  ]
                }
              },
              "lesson": {
                "id": "set-representation-description-q14",
                "title": "研究变换封闭的有限集合",
                "problem": {
                  "lines": [
                    {
                      "text": "设集合 A 由实数组成，并满足：若 \\(x\\in A\\)（\\(x\\ne0,1\\)），则 \\(\\frac{1}{1-x}\\in A\\)。",
                      "html": "设集合 A 由实数组成，并满足：若 <span class=\"inline-math\">x∈ A</span>（<span class=\"inline-math\">x≠0,1</span>），则 <span class=\"inline-math\"><span class=\"math-fraction\"><span class=\"math-numerator\">1</span><span class=\"math-denominator\">1-x</span></span>∈ A</span>。"
                    },
                    {
                      "text": "（1）若 \\(2\\in A\\)，证明 A 中还有另外两个元素；（2）A 是否可能为双元素集合；（3）若 A 中元素不超过 8 个，元素和为 \\(\\frac{14}3\\)，且某个元素的平方等于所有元素的积，求 A。",
                      "html": "（1）若 <span class=\"inline-math\">2∈ A</span>，证明 A 中还有另外两个元素；（2）A 是否可能为双元素集合；（3）若 A 中元素不超过 8 个，元素和为 <span class=\"inline-math\"><span class=\"math-fraction\"><span class=\"math-numerator\">14</span><span class=\"math-denominator\">3</span></span></span>，且某个元素的平方等于所有元素的积，求 A。"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-representation-description-q14.html"
              }
            },
            {
              "group": "区间表示法",
              "title": "把四个实数集合写成区间",
              "numberLabel": "练习 9 · 1",
              "display": "featured",
              "hints": [
                "先求取值范围，再判断端点能否取到。",
                "四个小问分别填写对应区间。"
              ],
              "answerSchema": {
                "type": "multipart-exact",
                "layout": "per-part",
                "expected": [
                  {
                    "label": "（1）",
                    "prompt": "\\(\\{x\\mid |x|\\le1\\}\\)",
                    "aliases": [
                      "[-1,1]"
                    ],
                    "promptHtml": "<span class=\"inline-math\">{x| |x|≤1}</span>"
                  },
                  {
                    "label": "（2）",
                    "prompt": "\\(\\{y\\mid y=\\sqrt{x}+2\\}\\)",
                    "aliases": [
                      "[2,∞)"
                    ],
                    "promptHtml": "<span class=\"inline-math\">{y| y=<span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">x</span></span>+2}</span>"
                  },
                  {
                    "label": "（3）",
                    "prompt": "\\(\\{y\\mid y=-x^2+2x\\}\\)",
                    "aliases": [
                      "(-∞,1]"
                    ],
                    "promptHtml": "<span class=\"inline-math\">{y| y=-x<sup>2</sup>+2x}</span>"
                  },
                  {
                    "label": "（4）",
                    "prompt": "\\(\\{y\\mid y=x^2-2x+1,x>0\\}\\)",
                    "aliases": [
                      "[0,∞)"
                    ],
                    "promptHtml": "<span class=\"inline-math\">{y| y=x<sup>2</sup>-2x+1,x&gt;0}</span>"
                  }
                ],
                "input": {
                  "mode": "math-expression",
                  "placeholder": "填写对应区间",
                  "keyboard": [
                    "interval",
                    "brackets",
                    "comma",
                    "semicolon",
                    "negative",
                    "digits",
                    "infinity"
                  ]
                }
              },
              "lesson": {
                "id": "set-representation-interval-q01",
                "title": "把四个实数集合写成区间",
                "problem": {
                  "lines": [
                    {
                      "text": "请用区间法表示下列集合：",
                      "html": "请用区间法表示下列集合："
                    },
                    {
                      "text": "（1）\\(\\{x\\mid |x|\\le1\\}\\)；（2）\\(\\{y\\mid y=\\sqrt{x}+2\\}\\)；（3）\\(\\{y\\mid y=-x^2+2x\\}\\)；（4）\\(\\{y\\mid y=x^2-2x+1,x>0\\}\\)。",
                      "html": "（1）<span class=\"inline-math\">{x| |x|≤1}</span>；（2）<span class=\"inline-math\">{y| y=<span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">x</span></span>+2}</span>；（3）<span class=\"inline-math\">{y| y=-x<sup>2</sup>+2x}</span>；（4）<span class=\"inline-math\">{y| y=x<sup>2</sup>-2x+1,x&gt;0}</span>。"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-representation-interval-q01.html"
              }
            },
            {
              "group": "Venn 图法",
              "title": "由 Venn 图阴影确定区间",
              "numberLabel": "练习 10 · 1",
              "display": "featured",
              "hints": [
                "阴影表示 B 中不属于 A 的部分。",
                "逐个判断 0 和 1 是否是端点。"
              ],
              "answerSchema": {
                "type": "single-choice",
                "expected": "B"
              },
              "lesson": {
                "id": "set-representation-venn-q01",
                "title": "由 Venn 图阴影确定区间",
                "problem": {
                  "lines": [
                    {
                      "text": "已知全集为实数集，\\(A=\\{x\\mid1<x<2\\}\\)，\\(B=\\{x\\mid0<x\\le\\frac{3}{2}\\}\\)。图中阴影表示 B 中不属于 A 的部分，求该集合。",
                      "html": "已知全集为实数集，<span class=\"inline-math\">A={x|1&lt;x&lt;2}</span>，<span class=\"inline-math\">B={x|0&lt;x≤<span class=\"math-fraction\"><span class=\"math-numerator\">3</span><span class=\"math-denominator\">2</span></span>}</span>。图中阴影表示 B 中不属于 A 的部分，求该集合。"
                    },
                    {
                      "figureHtml": "\n      <figure class=\"set-figure\">\n        <svg viewBox=\"0 0 480 250\" role=\"img\" aria-label=\"阴影为 B 去掉 A 的部分\">\n          <defs>\n            <mask id=\"venn-b-minus-a-mask\" maskUnits=\"userSpaceOnUse\" x=\"0\" y=\"0\" width=\"480\" height=\"250\">\n              <rect x=\"0\" y=\"0\" width=\"480\" height=\"250\" fill=\"black\"/>\n              <circle cx=\"267\" cy=\"120\" r=\"76\" fill=\"white\"/>\n              <circle cx=\"213\" cy=\"120\" r=\"76\" fill=\"black\"/>\n            </mask>\n          </defs>\n          <rect class=\"set-figure-universe\" x=\"34\" y=\"22\" width=\"412\" height=\"202\" rx=\"4\"/>\n          <rect class=\"set-figure-shade\" x=\"0\" y=\"0\" width=\"480\" height=\"250\" mask=\"url(#venn-b-minus-a-mask)\"/>\n          <circle class=\"set-figure-set\" cx=\"213\" cy=\"120\" r=\"76\"/>\n          <circle class=\"set-figure-set\" cx=\"267\" cy=\"120\" r=\"76\"/>\n          <text x=\"192\" y=\"205\">A</text>\n          <text x=\"285\" y=\"205\">B</text>\n          <text x=\"414\" y=\"48\">U</text>\n        </svg>\n        \n      </figure>\n    ",
                      "ariaLabel": "阴影为 B 去掉 A 的部分"
                    },
                    {
                      "text": "A. \\([0,1]\\)　B. \\((0,1]\\)　C. \\([0,1)\\)　D. \\((0,1)\\)",
                      "html": "A. <span class=\"inline-math\">[0,1]</span>　B. <span class=\"inline-math\">(0,1]</span>　C. <span class=\"inline-math\">[0,1)</span>　D. <span class=\"inline-math\">(0,1)</span>"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-representation-venn-q01.html"
              }
            },
            {
              "group": "Venn 图法",
              "title": "由离散全集读取 Venn 图阴影",
              "numberLabel": "练习 10 · 2",
              "display": "featured",
              "hints": [
                "先列出 A，再去掉 A 与 B 的公共元素。"
              ],
              "answerSchema": {
                "type": "single-choice",
                "expected": "A"
              },
              "lesson": {
                "id": "set-representation-venn-q02",
                "title": "由离散全集读取 Venn 图阴影",
                "problem": {
                  "lines": [
                    {
                      "text": "已知全集 \\(U=\\{0,1,2,3,4,5,6,7,8\\}\\)，\\(A=\\{x\\in\\mathbb N\\mid x<5\\}\\)，\\(B=\\{1,3,5,7,8\\}\\)。图中阴影表示 A 中不属于 B 的部分。",
                      "html": "已知全集 <span class=\"inline-math\">U={0,1,2,3,4,5,6,7,8}</span>，<span class=\"inline-math\">A={x∈<span class=\"math-blackboard\">ℕ</span>| x&lt;5}</span>，<span class=\"inline-math\">B={1,3,5,7,8}</span>。图中阴影表示 A 中不属于 B 的部分。"
                    },
                    {
                      "figureHtml": "\n      <figure class=\"set-figure\">\n        <svg viewBox=\"0 0 480 250\" role=\"img\" aria-label=\"阴影为 A 去掉 B 的部分\">\n          <defs>\n            <mask id=\"venn-a-minus-b-mask\" maskUnits=\"userSpaceOnUse\" x=\"0\" y=\"0\" width=\"480\" height=\"250\">\n              <rect x=\"0\" y=\"0\" width=\"480\" height=\"250\" fill=\"black\"/>\n              <circle cx=\"213\" cy=\"120\" r=\"76\" fill=\"white\"/>\n              <circle cx=\"267\" cy=\"120\" r=\"76\" fill=\"black\"/>\n            </mask>\n          </defs>\n          <rect class=\"set-figure-universe\" x=\"34\" y=\"22\" width=\"412\" height=\"202\" rx=\"4\"/>\n          <rect class=\"set-figure-shade\" x=\"0\" y=\"0\" width=\"480\" height=\"250\" mask=\"url(#venn-a-minus-b-mask)\"/>\n          <circle class=\"set-figure-set\" cx=\"213\" cy=\"120\" r=\"76\"/>\n          <circle class=\"set-figure-set\" cx=\"267\" cy=\"120\" r=\"76\"/>\n          <text x=\"192\" y=\"205\">A</text>\n          <text x=\"285\" y=\"205\">B</text>\n          <text x=\"414\" y=\"48\">U</text>\n        </svg>\n        \n      </figure>\n    ",
                      "ariaLabel": "阴影为 A 去掉 B 的部分"
                    },
                    {
                      "text": "A. \\(\\{0,2,4\\}\\)　B. \\(\\{2,4\\}\\)　C. \\(\\{0,4\\}\\)　D. \\(\\{2,4,6\\}\\)",
                      "html": "A. <span class=\"inline-math\">{0,2,4}</span>　B. <span class=\"inline-math\">{2,4}</span>　C. <span class=\"inline-math\">{0,4}</span>　D. <span class=\"inline-math\">{2,4,6}</span>"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-representation-venn-q02.html"
              }
            },
            {
              "group": "Venn 图法",
              "title": "统计两项比赛都参加的人数",
              "numberLabel": "练习 11 · 1",
              "display": "featured",
              "hints": [
                "使用两集合容斥公式。"
              ],
              "answerSchema": {
                "type": "integer",
                "expected": "8",
                "input": {
                  "mode": "math-expression",
                  "placeholder": "填写人数",
                  "keyboard": [
                    "digits"
                  ]
                }
              },
              "lesson": {
                "id": "set-representation-venn-q03",
                "title": "用容斥原理统计两项比赛都参加的人数",
                "source": "2021 天津市第四十七中学秋季运动会测试",
                "problem": {
                  "lines": [
                    {
                      "text": "2021 年天津市第四十七中学秋季运动会，高一某班 41 名学生中有 10 名没有参加比赛；参加田赛的有 16 人，参加径赛的有 23 人。求田赛和径赛都参加的学生人数。",
                      "html": "2021 年天津市第四十七中学秋季运动会，高一某班 41 名学生中有 10 名没有参加比赛；参加田赛的有 16 人，参加径赛的有 23 人。求田赛和径赛都参加的学生人数。"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-representation-venn-q03.html"
              }
            },
            {
              "group": "Venn 图法",
              "title": "求三天售出商品种类的最小值",
              "numberLabel": "练习 11 · 2",
              "display": "featured",
              "hints": [
                "让第一天和第三天在第二天之外尽量重合。"
              ],
              "answerSchema": {
                "type": "multipart-exact",
                "expected": [
                  {
                    "aliases": [
                      "16"
                    ]
                  },
                  {
                    "aliases": [
                      "29"
                    ]
                  }
                ],
                "input": {
                  "mode": "math-expression",
                  "placeholder": "依次填写两问答案",
                  "keyboard": [
                    "digits",
                    "semicolon"
                  ]
                }
              },
              "lesson": {
                "id": "set-representation-venn-q04",
                "title": "求三天售出商品种类的最小值",
                "problem": {
                  "lines": [
                    {
                      "text": "某网店连续三天售出商品的种类数分别为 19、13、18；前两天都售出的有 3 种，后两天都售出的有 4 种。",
                      "html": "某网店连续三天售出商品的种类数分别为 19、13、18；前两天都售出的有 3 种，后两天都售出的有 4 种。"
                    },
                    {
                      "text": "（1）第一天售出但第二天未售出的商品有多少种？（2）这三天售出的商品最少有多少种？",
                      "html": "（1）第一天售出但第二天未售出的商品有多少种？（2）这三天售出的商品最少有多少种？"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-representation-venn-q04.html"
              }
            }
          ],
          "summary": "集合共有列举法、描述法、区间表示法和 Venn 图法四种常用表示方式。列举法适合元素较少或可以逐一确定的集合；描述法突出代表元素与共同特征；区间法专门表示连续实数集合；Venn 图法用图形直观呈现集合及其关系。",
          "summaryHtml": "集合共有列举法、描述法、区间表示法和 Venn 图法四种常用表示方式。列举法适合元素较少或可以逐一确定的集合；描述法突出代表元素与共同特征；区间法专门表示连续实数集合；Venn 图法用图形直观呈现集合及其关系。"
        },
        {
          "id": "practice",
          "label": "实战练习",
          "type": "assessment",
          "status": "published",
          "description": "综合判断集合的确定性、元素关系、互异性和表示方法。",
          "items": [
            {
              "number": 1,
              "status": "published",
              "numberLabel": "第 1 题",
              "hints": [
                "逐项判断描述对象的标准是否明确。"
              ],
              "answerSchema": {
                "type": "single-choice",
                "expected": "C"
              },
              "lesson": {
                "id": "set-practice-q01",
                "title": "实战练习 1：判断对象能否构成集合",
                "problem": {
                  "lines": [
                    {
                      "text": "以下四组对象，能构成集合的是：",
                      "html": "以下四组对象，能构成集合的是："
                    },
                    {
                      "text": "A. 最大的正实数　　B. 最小的整数　　C. 平方等于 1 的实数　　D. 最接近 1 的实数",
                      "html": "A. 最大的正实数　　B. 最小的整数　　C. 平方等于 1 的实数　　D. 最接近 1 的实数"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-practice-q01.html"
              }
            },
            {
              "number": 2,
              "status": "published",
              "numberLabel": "第 2 题",
              "hints": [
                "先化简每个数，再判断它与相应数集的关系。"
              ],
              "answerSchema": {
                "type": "single-choice",
                "expected": "B"
              },
              "lesson": {
                "id": "set-practice-q02",
                "title": "实战练习 2：判断元素与数集的关系",
                "problem": {
                  "lines": [
                    {
                      "text": "给出下列关系：① \\(|-2|\\in\\mathbb N^*\\)；② \\(0\\notin\\mathbb Z\\)；③ \\(\\sqrt{2}\\in\\mathbb Q\\)；④ \\(-\\frac{3}{2}\\in\\mathbb R\\)。其中错误的个数是：",
                      "html": "给出下列关系：① <span class=\"inline-math\">|-2|∈<span class=\"math-blackboard\">ℕ</span><sup>*</sup></span>；② <span class=\"inline-math\">0<span class=\"math-notin\" role=\"img\" aria-label=\"不属于\"><svg viewBox=\"0 0 18 18\" aria-hidden=\"true\" focusable=\"false\"><path d=\"M15 3H9C5.3 3 3 5.5 3 9s2.3 6 6 6h6M3.7 9h10.8M4.5 16L14 2\"/></svg></span><span class=\"math-blackboard\">ℤ</span></span>；③ <span class=\"inline-math\"><span class=\"math-radical\"><span class=\"math-radical-symbol\">√</span><span class=\"math-radicand\">2</span></span>∈<span class=\"math-blackboard\">ℚ</span></span>；④ <span class=\"inline-math\">-<span class=\"math-fraction\"><span class=\"math-numerator\">3</span><span class=\"math-denominator\">2</span></span>∈<span class=\"math-blackboard\">ℝ</span></span>。其中错误的个数是："
                    },
                    {
                      "text": "A. 1　　B. 2　　C. 3　　D. 4",
                      "html": "A. 1　　B. 2　　C. 3　　D. 4"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-practice-q02.html"
              }
            },
            {
              "number": 3,
              "status": "published",
              "numberLabel": "第 3 题",
              "hints": [
                "先分别令两个含参元素等于 1，求出候选值。",
                "再把候选值代回集合，检查三个元素是否互不相同。"
              ],
              "answerSchema": {
                "type": "single-choice",
                "expected": "D"
              },
              "lesson": {
                "id": "set-practice-q03",
                "title": "实战练习 3：由元素属于集合求参数",
                "problem": {
                  "lines": [
                    {
                      "text": "若 \\(1\\in\\{2,a^2-a-1,a^2+1\\}\\)，则 \\(a=\\)（　）。",
                      "html": "若 <span class=\"inline-math\">1∈{2,a<sup>2</sup>-a-1,a<sup>2</sup>+1}</span>，则 <span class=\"inline-math\">a=</span>（　）。"
                    },
                    {
                      "text": "A. \\(0\\) 或 \\(-1\\)　　B. \\(0\\) 或 \\(1\\)　　C. \\(-1\\) 或 \\(2\\)　　D. \\(0\\) 或 \\(2\\)",
                      "html": "A. <span class=\"inline-math\">0</span> 或 <span class=\"inline-math\">-1</span>　　B. <span class=\"inline-math\">0</span> 或 <span class=\"inline-math\">1</span>　　C. <span class=\"inline-math\">-1</span> 或 <span class=\"inline-math\">2</span>　　D. <span class=\"inline-math\">0</span> 或 <span class=\"inline-math\">2</span>"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-practice-q03.html"
              }
            },
            {
              "number": 4,
              "status": "published",
              "numberLabel": "第 4 题",
              "hints": [
                "令 d=5-a，把分式为正整数转化为 d 是 6 的正因数。"
              ],
              "answerSchema": {
                "type": "single-choice",
                "expected": "D"
              },
              "lesson": {
                "id": "set-practice-q04",
                "title": "实战练习 4：用列举法表示集合",
                "problem": {
                  "lines": [
                    {
                      "text": "已知集合 \\(M=\\left\\{a\\middle|\\frac{6}{5-a}\\in\\mathbb N^*，且a\\in\\mathbb Z\\right\\}\\)，则 \\(M\\) 等于：",
                      "html": "已知集合 <span class=\"inline-math\">M={a|<span class=\"math-fraction\"><span class=\"math-numerator\">6</span><span class=\"math-denominator\">5-a</span></span>∈<span class=\"math-blackboard\">ℕ</span><sup>*</sup>，且a∈<span class=\"math-blackboard\">ℤ</span>}</span>，则 <span class=\"inline-math\">M</span> 等于："
                    },
                    {
                      "text": "A. \\(\\{2,3\\}\\)　　B. \\(\\{1,2,3,4\\}\\)　　C. \\(\\{1,2,3,6\\}\\)　　D. \\(\\{-1,2,3,4\\}\\)",
                      "html": "A. <span class=\"inline-math\">{2,3}</span>　　B. <span class=\"inline-math\">{1,2,3,4}</span>　　C. <span class=\"inline-math\">{1,2,3,6}</span>　　D. <span class=\"inline-math\">{-1,2,3,4}</span>"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-practice-q04.html"
              }
            },
            {
              "number": 5,
              "status": "published",
              "numberLabel": "第 5 题",
              "hints": [
                "先讨论 a=0；当 a≠0 时再使用判别式。"
              ],
              "answerSchema": {
                "type": "exact-expression",
                "expected": [
                  "a=0或a≥9/8",
                  "0∪[9/8,+∞)",
                  "{0}∪[9/8,+∞)",
                  "0或a≥9/8"
                ],
                "input": {
                  "mode": "math-expression",
                  "placeholder": "填写 a 的取值范围",
                  "keyboard": [
                    "a",
                    "real",
                    "in",
                    "equals",
                    "greater-equal",
                    "union",
                    "set-braces",
                    "brackets",
                    "interval",
                    "comma",
                    "digits",
                    "fraction",
                    "infinity"
                  ]
                }
              },
              "lesson": {
                "id": "set-practice-q05",
                "title": "实战练习 5：根集至多含一个元素",
                "problem": {
                  "lines": [
                    {
                      "text": "已知集合 \\(A=\\{x\\mid ax^2-3x+2=0\\}\\) 至多有一个元素，则 \\(a\\) 的取值范围是______。",
                      "html": "已知集合 <span class=\"inline-math\">A={x| ax<sup>2</sup>-3x+2=0}</span> 至多有一个元素，则 <span class=\"inline-math\">a</span> 的取值范围是______。"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-practice-q05.html"
              }
            },
            {
              "number": 6,
              "status": "published",
              "numberLabel": "第 6 题",
              "hints": [
                "先解方程组，再把有序数对作为一个整体放进集合。"
              ],
              "answerSchema": {
                "type": "exact-expression",
                "expected": [
                  "{(2,-1)}",
                  "P={(2,-1)}"
                ],
                "input": {
                  "mode": "math-expression",
                  "placeholder": "用列举法填写集合 P",
                  "keyboard": [
                    "set-braces",
                    "interval",
                    "comma",
                    "digits",
                    "negative",
                    "equals"
                  ]
                }
              },
              "lesson": {
                "id": "set-practice-q06",
                "title": "实战练习 6：用列举法表示点集",
                "problem": {
                  "lines": [
                    {
                      "text": "集合 \\(P=\\{(x,y)\\mid x+y=1，x-y-3=0\\}\\) 可以用列举法表示为______。",
                      "html": "集合 <span class=\"inline-math\">P={(x,y)| x+y=1，x-y-3=0}</span> 可以用列举法表示为______。"
                    }
                  ]
                },
                "solutionPath": "problems/senior-high/sets/set-concepts-and-representation/set-practice-q06.html"
              }
            }
          ]
        }
      ]
    }
  ]
};
