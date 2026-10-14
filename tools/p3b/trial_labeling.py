"""Chinese adapter for this repair preview, separate from frozen V2 decisions."""

import copy
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from PIL import Image, ImageTk, ImageDraw, ImageFont

from common import atomic_json, read, read_rows
from target_view import target_overlay, target_zoom, annotated_zoom

CLASSES={1:"SINGLE_PHYSICAL_STROKE",2:"TRUE_PARALLEL_STRUCTURE",3:"OTHER"}
REASONS=("", "不知道标线对应哪个源对象", "对象看清了，但类别判断不了",
         "现有分类规则没有覆盖", "其他/暂时说不清")
PENDING={"preview-011":"轴线/轴网边缘的任务范围",
         "preview-013":"设备安装详图边界的任务范围",
         "preview-021":"专业管线与建筑轴线混合对象的判定规则"}
RULES="""判断被指出的源图笔画或对象，不是数红蓝线，不是数整幅裁片中的线，也不直接决定DXF如何合并。

1＝一条结构/规则笔画。两条候选边缘可以来自同一根有宽度的笔画。
2＝两条需要分别保留的独立结构/规则笔画或边界。可以同属一面墙或一个楼梯；同属一个对象不代表合并为一根线。
3＝明确不属于本次线结构分类对象。包括文字、数字、字符/符号内部笔画、图形、填充/阴影、伪影等。“不是本任务”不代表产品可以删除它。

依据：LABELING-CONTRACT-V2.md §Stage 1: physical class，第1–3项；REPORT.md §Label rubric and provenance，类别表。表格/图框成员可以属于规则笔画，仍由人判断当前目标。
三分类范围：VALIDATION-SUSPECT-REVIEW-FINAL.md §AMBIGUOUS training policy。旧AMBIGUOUS记录保留；本批暂缓不自动写成AMBIGUOUS。

尺寸线、轴线、引出线、安装详图边界：上述契约未明确其任务范围，规则待定。011、013、021已标出相关范围问题；其他项如遇未覆盖规则也可直接暂缓。
规则待定项的1/2/3只保存观察，category保持空值，不计明确分类，不生成监督训练硬标签。

PAIR/SINGLE/CONTROL是提名形式；profile和STRUCTURAL GEOMETRY字段不是人工类别。阴影线对和小墨迹区域都不预填答案。
不知道标线指谁，可以直接暂不能判断。只有能确认提名错误时才选候选明确指错。两者都不强制说明理由。
本批用途为开发已接触/修复试用，不导入旧94/50、不训练、不创建后续复核任务。"""


def load_trial(manifest):
    base=Path(manifest).resolve().parent
    rows=read_rows(manifest)
    ids=[r["sample_id"] for r in rows]
    index_ids=[r["sample_id"] for r in read(base/"candidate-index.json")["rows"]]
    html_ids=re.findall(r'<article id="(preview-\d+)"',(base/"index.html").read_text(encoding="utf-8"))
    if ids!=index_ids or ids!=html_ids or len(ids)!=len(set(ids)):
        raise ValueError("当前HTML、索引和队列成员/顺序不一致；未覆盖任何记录")
    if {"preview-004","preview-022"}&set(ids):
        raise ValueError("排除项不能进入本次试标")
    for row in rows:
        if row.get("purpose")!="repair_preview_only" or row.get("training_authorized"):
            raise ValueError("只接受独立修复预览，不能复用冻结训练/验证状态")
        for key in ("crop","context_raw","page_position"):
            with Image.open(base/row["preview_files"][key]) as im: im.load()
    return rows,base


def target_record(row):
    fields=("sample_id","source_drawing_id","source_entry_id","source_path","source_relative_path",
            "source_page","source_bbox","candidate_geometry_ids","candidate_geometry","target_roi",
            "content_source","container_identity")
    return {k:copy.deepcopy(row.get(k)) for k in fields}


def prepare_display(manifest):
    """Synchronize the contact sheet and entry using existing crop pixels only."""
    rows,base=load_trial(manifest)
    history=base/"overview-old-22.jpg"
    if not history.exists():
        (base/"overview.jpg").rename(history)
        old_html=base/"initial-index.html"
        text=old_html.read_text(encoding="utf-8").replace('href="overview.jpg"','href="overview-old-22.jpg"')
        old_html.write_text(text.replace('<h1>P3B 小范围修复裁切预览</h1>',
            '<h1>历史版：初版22个候选；004和022已排除，不用于本次试标</h1>'),encoding="utf-8")
    font=ImageFont.truetype("C:/Windows/Fonts/msyh.ttc",18)
    sheet=Image.new("RGB",(1500,80+((len(rows)+4)//5)*330),"#eef1f4")
    draw=ImageDraw.Draw(sheet)
    draw.text((20,14),f"当前{len(rows)}个候选 · 中文小批试标 · 无预填类别",font=font,fill="#172a36")
    draw.text((20,42),"004、022已排除；编号保留缺口。原图与上下文请在试标窗口查看。",font=font,fill="#475b6a")
    for i,row in enumerate(rows):
        x=(i%5)*300+20;y=(i//5)*330+80
        draw.text((x,y),f"第{i+1}项/{len(rows)} · {row['sample_id']}",font=font,fill="#172a36")
        with Image.open(base/row["preview_files"]["crop"]) as im:gray=im.convert("L")
        sheet.paste(target_overlay(gray,row,1,trial=True,members="all"),(x,y+30))
        draw.text((x,y+290),f"{row['short_title']} · P{row['source_page']}",font=font,fill="#172a36")
    sheet.save(base/"overview.jpg",quality=93)
    entry='<p id="current-trial-entry"><b>当前20个候选的小批试标：</b><a href="launch-trial-labeling.ps1">本地Tk启动入口</a> · <a href="overview.jpg">当前20项总览</a>。保存到trial-labels.json。旧22项总览：overview-old-22.jpg，仅供历史查看。</p>'
    html_path=base/"index.html";text=html_path.read_text(encoding="utf-8")
    if 'id="current-trial-entry"' not in text:html_path.write_text(text.replace('<header><h1>',entry+'<header><h1>',1),encoding="utf-8")
    index=read(base/"candidate-index.json")
    index["presentation"]={"current_overview":"overview.jpg","historical_overview":"overview-old-22.jpg",
        "historical_overview_status":"旧22项，非当前入口，004/022已排除",
        "member_ids":[r["sample_id"] for r in rows],"trial_entry":"launch-trial-labeling.ps1",
        "trial_state":"trial-labels.json","scope_rule_pending":PENDING}
    atomic_json(base/"candidate-index.json",index)
    run=read(base/"run.json")
    run["small_trial"]={"queue_count":len(rows),"member_ids":[r["sample_id"] for r in rows],
        "excluded_ids":["preview-004","preview-022"],"purpose":"development_accessed_repair_trial",
        "entry":"launch-trial-labeling.ps1","state":"trial-labels.json","rules_pending":PENDING,
        "scope_unresolved_objects":["尺寸线","轴线","引出线","安装详图边界"],
        "checks":"9 local tests using actual 20 assets and isolated states, including hidden Tk callbacks/save failure/resume",
        "UI_LAUNCHED":"NOT_STARTED","new_sampling":False,"new_crops":False,"training":False}
    atomic_json(base/"run.json",run)
    return base/"overview.jpg"


class TrialStore:
    """Commit memory/cursor only after flushed atomic saving succeeds. No hashes."""
    def __init__(self,path,rows,annotator="local-reviewer"):
        self.path=Path(path).resolve(); self.rows=rows; self.annotator=annotator
        self.session_id=str(uuid.uuid4())
        targets=[target_record(r) for r in rows]
        self.state=read(self.path) if self.path.exists() else {
            "schema_version":"p3b-repair-trial-labels-v1","purpose":"development_accessed_repair_trial",
            "training_authorized":False,"dataset_split":"unassigned_preview",
            "queue_targets":targets,"answers":{},"drafts":{},"views":{},"history":[],
            "cursor_index":0,"cursor_sample_id":rows[0]["sample_id"] if rows else None,"revision":0,
            "scope_rule_pending":PENDING,"scope_unresolved_objects":["尺寸线","轴线","引出线","安装详图边界"]}
        if (self.state.get("schema_version")!="p3b-repair-trial-labels-v1"
            or self.state.get("queue_targets")!=targets or self.state.get("training_authorized")
            or self.state.get("purpose")!="development_accessed_repair_trial"):
            raise ValueError("已有回答绑定不同目标或用途；没有清空或覆盖")
        if not 0<=self.state["cursor_index"]<=len(rows): raise ValueError("已有当前位置不合法，未改写")

    def _commit(self,state,action,**fields):
        state["revision"]+=1
        state["history"].append({"action":action,"session_id":self.session_id,
            "timestamp_utc":datetime.now(timezone.utc).isoformat(),**fields})
        atomic_json(self.path,state)
        self.state=state

    def _cursor(self,state,index):
        if not 0<=index<=len(self.rows): raise ValueError("位置越界")
        state["cursor_index"]=index
        state["cursor_sample_id"]=self.rows[index]["sample_id"] if index<len(self.rows) else None

    def startup(self,mapped):
        state=copy.deepcopy(self.state)
        state["last_ui_startup"]={"session_id":self.session_id,"mapped_window":bool(mapped),
                                  "tool":"label_ui.py --mode repair-trial","answer_created":False}
        self._commit(state,"ui_opened",sample_id=state["cursor_sample_id"],mapped_window=bool(mapped))

    def counts(self):
        answers=self.state["answers"]
        statuses=Counter(a["status"] for a in answers.values())
        return {"processed":sum(bool(a["processed"]) for a in answers.values()),
                "classified":sum(bool(a["category_assigned"]) for a in answers.values()),
                "deferred":statuses["deferred"],"rule_pending_observations":statuses["rule_pending_observation"],
                "paused":statuses["deferred"]+statuses["rule_pending_observation"],
                "invalid_candidates":statuses["invalid_nomination"],"total":len(self.rows)}

    def answer(self,index,status,code=None,reason=None,note=""):
        if status not in ("classified","deferred","invalid_nomination"): raise ValueError("未知处理状态")
        if status=="classified" and code not in CLASSES: raise ValueError("类别只接受1/2/3")
        if reason is not None and reason not in REASONS[1:]: raise ValueError("未知可选原因")
        state=copy.deepcopy(self.state);row=self.rows[index];sid=row["sample_id"]
        pending=sid in PENDING
        assigned=status=="classified" and not pending
        answer={"processed":True,"category_assigned":assigned,
                "category":CLASSES[code] if assigned else None,"human_code":code if assigned else None,
                "observation_code":code if status=="classified" and pending else None,
                "status":"rule_pending_observation" if status=="classified" and pending else status,
                "optional_reason":reason,"observation":note,"scope_rule_pending":PENDING.get(sid),
                "annotator":self.annotator,"timestamp_utc":datetime.now(timezone.utc).isoformat(),
                "training_authorized":False,"intentional_review":False}
        previous=state["answers"].get(sid)
        state["answers"][sid]=answer;state["drafts"].pop(sid,None)
        next_index=index+1
        while next_index<len(self.rows) and self.rows[next_index]["sample_id"] in state["answers"]: next_index+=1
        self._cursor(state,next_index)
        self._commit(state,"answer_changed" if previous else "answer_saved",sample_id=sid,answer=answer,previous_answer=previous)

    def navigate(self,index,note="",reason=None):
        state=copy.deepcopy(self.state);sid=state["cursor_sample_id"]
        if sid: state["drafts"][sid]={"observation":note,"optional_reason":reason}
        self._cursor(state,index)
        self._commit(state,"navigate",sample_id=state["cursor_sample_id"],queue_rank=index+1 if index<len(self.rows) else None)

    def view(self,sid,**fields):
        state=copy.deepcopy(self.state);state["views"].setdefault(sid,{}).update(fields)
        self._commit(state,"display_changed",sample_id=sid,display=fields)

    def finish(self,note="",reason=None):
        state=copy.deepcopy(self.state);sid=state["cursor_sample_id"]
        if sid: state["drafts"][sid]={"observation":note,"optional_reason":reason}
        self._commit(state,"save_and_end",sample_id=sid,counts=self.counts())


class RepairTrialApp:
    def __init__(self,window,manifest,labels,annotator,patch_root=None):
        self.rows,self.base=load_trial(manifest)
        if patch_root and Path(patch_root).resolve()!=self.base: raise ValueError("试标必须显示本批既有图片")
        if Path(labels).resolve()!=self.base/"trial-labels.json": raise ValueError("本批保存到独立trial-labels.json，旧标签不得覆盖")
        self.window=window;self.store=TrialStore(labels,self.rows,annotator);self.popups=[];self.images=[]
        width=min(1250,window.winfo_screenwidth()-50);height=min(920,window.winfo_screenheight()-90)
        self.display_scale=1.5 if height>=830 else 1
        window.title(f"Image to CAD — 当前{len(self.rows)}个候选 · 中文小批试标")
        window.geometry(f"{width}x{height}")
        self.progress=tk.StringVar();self.title=tk.StringVar();self.source=tk.StringVar();self.scope=tk.StringVar()
        self.saved=tk.StringVar(value="尚未新增回答。可直接暂缓，不要求20个确定标签。")
        self.reason=tk.StringVar();self.observation=tk.StringVar();self.current_answer=tk.StringVar()
        tk.Label(window,text="判断被指出的源图笔画或对象；不数彩线，不数整幅裁片的线，不直接决定DXF合并。",font=("Microsoft YaHei",11)).pack(pady=(8,2))
        tk.Label(window,text="1：一条笔画（可有两侧边缘）　2：两条独立笔画/边界（可同属一个对象）　3：非本任务对象",font=("Microsoft YaHei",10)).pack()
        tk.Button(window,text="展开分类规则与出处",command=self.rules).pack(pady=2)
        tk.Label(window,textvariable=self.progress,font=("Microsoft YaHei",11)).pack()
        tk.Label(window,textvariable=self.title,font=("Microsoft YaHei",12,"bold")).pack()
        tk.Label(window,textvariable=self.source,font=("Microsoft YaHei",9),wraplength=width-50).pack()
        tk.Label(window,textvariable=self.scope,font=("Microsoft YaHei",10),foreground="#8b4700",wraplength=width-40).pack(pady=3)
        panes=tk.Frame(window);panes.pack()
        left=tk.Frame(panes);right=tk.Frame(panes);left.pack(side="left",padx=10);right.pack(side="left",padx=10)
        tk.Label(left,text="原始灰度裁块").pack();tk.Label(right,text="当前目标叠加；A红、B蓝").pack()
        self.left=tk.Label(left);self.right=tk.Label(right);self.left.pack();self.right.pack()
        tk.Label(window,text="起/止是同一成员的两个端点，不是两根线或流向。放大仅改变显示。",font=("Microsoft YaHei",9)).pack()
        layers=tk.Frame(window);layers.pack(pady=4);self.layer_buttons={}
        for mode,text in (("none","原图"),("A","只看A"),("B","只看B"),("all","两者对照")):
            button=tk.Button(layers,text=text,command=lambda m=mode:self.layer(m));button.pack(side="left",padx=3);self.layer_buttons[mode]=button
        for text,callback in (("4倍",lambda:self.zoom(4)),("8倍",lambda:self.zoom(8)),("上下文",lambda:self.context()),("整页定位",lambda:self.whole_page()),("展开提名信息",self.details)):
            tk.Button(layers,text=text,command=callback).pack(side="left",padx=3)
        choices=tk.Frame(window);choices.pack(pady=5);self.answer_buttons=[]
        for status,code,text in (("classified",1,"1 — 一条结构/规则笔画"),("classified",2,"2 — 两条独立结构/规则笔画"),
                                 ("classified",3,"3 — 非本任务对象"),("deferred",None,"暂不能判断"),("invalid_nomination",None,"候选明确指错")):
            b=tk.Button(choices,text=text,command=lambda s=status,c=code:self.choose(s,c),padx=6,pady=6);b.pack(side="left",padx=3);self.answer_buttons.append(b)
        secondary=tk.Frame(window);secondary.pack(pady=3)
        tk.Label(secondary,text="暂缓原因（可选）").pack(side="left")
        ttk.Combobox(secondary,textvariable=self.reason,values=REASONS,state="readonly",width=29).pack(side="left",padx=4)
        tk.Label(secondary,text="观察（可选）").pack(side="left")
        ttk.Entry(secondary,textvariable=self.observation,width=38).pack(side="left")
        tk.Label(window,textvariable=self.current_answer,font=("Microsoft YaHei",9)).pack()
        nav=tk.Frame(window);nav.pack(pady=3)
        tk.Button(nav,text="返回修改",command=lambda:self.navigate(-1)).pack(side="left",padx=4)
        tk.Button(nav,text="下一项（不新增回答）",command=lambda:self.navigate(1)).pack(side="left",padx=4)
        tk.Button(nav,text="保存并结束",command=self.finish).pack(side="left",padx=15)
        tk.Label(window,textvariable=self.saved,foreground="#235c36",wraplength=width-40).pack()
        tk.Label(window,text="快捷键：1/2/3分类；空格暂缓；X明确指错；退格返回修改。无需先V，也无需区分U与4。",font=("Microsoft YaHei",9)).pack(pady=2)
        for key,code in (("1",1),("2",2),("3",3)):
            window.bind(key,lambda e,c=code:self.key(e,lambda:self.choose("classified",c)))
        window.bind("<space>",lambda e:self.key(e,lambda:self.choose("deferred")))
        window.bind("x",lambda e:self.key(e,lambda:self.choose("invalid_nomination")))
        window.bind("X",lambda e:self.key(e,lambda:self.choose("invalid_nomination")))
        window.bind("<BackSpace>",lambda e:self.key(e,lambda:self.navigate(-1)))
        window.protocol("WM_DELETE_WINDOW",self.finish)
        self.show();window.update()
        try:self.store.startup(window.winfo_ismapped())
        except OSError as error:self.failure(error)

    @property
    def index(self): return self.store.state["cursor_index"]

    def key(self,event,callback):
        if isinstance(event.widget,(tk.Entry,ttk.Entry,ttk.Combobox,tk.Text)): return
        callback();return "break"

    def failure(self,error):
        self.saved.set("保存失败，仍停在当前项；没有显示已保存。")
        messagebox.showerror("保存失败",str(error)+"\n"+str(self.store.path),parent=self.window)

    def close_popups(self):
        for top in self.popups:
            if top.winfo_exists():top.destroy()
        self.popups=[]

    def show(self):
        self.close_popups();counts=self.store.counts()
        self.progress.set(f"已处理 {counts['processed']}/{counts['total']}　其中明确分类 {counts['classified']}　暂缓 {counts['paused']}（含规则待定观察）　明确错误 {counts['invalid_candidates']}")
        if self.index>=len(self.rows):
            self.title.set("当前队列已走完；不自动安排第二遍复核")
            self.source.set("可返回修改或保存并结束。暂缓不算确定标签。")
            self.scope.set("");self.left.configure(image="");self.right.configure(image="");self.current_answer.set("")
            for b in self.answer_buttons:b.configure(state="disabled")
            return
        row=self.rows[self.index];sid=row["sample_id"]
        self.title.set(f"第{self.index+1}项/{len(self.rows)}　{sid} · {row['short_title']}")
        self.source.set(f"{Path(row['source_relative_path']).name}　PDF物理第{row['source_page']}页 / {row['page_frame']['printed_sheet_or_atlas_page']}\n内容族：{row['source_family_id']}；用途：开发已接触／修复试用")
        self.scope.set("规则待定："+PENDING[sid]+"。1/2/3仅保存观察，不计明确分类。" if sid in PENDING else "规则未覆盖或对象无法判断时，直接暂缓；不据提名类型或测量字段填答案。")
        geometry=row["candidate_geometry"]
        self.layer_buttons["A"].configure(state="normal" if geometry else "disabled")
        self.layer_buttons["B"].configure(state="normal" if len(geometry)==2 else "disabled")
        self.layer_buttons["all"].configure(text="两者对照" if len(geometry)==2 else "显示A" if geometry else "目标框")
        self.mode=self.store.state["views"].get(sid,{}).get("layer","all")
        if self.mode=="B" and len(geometry)!=2:self.mode="all"
        with Image.open(self.base/row["preview_files"]["crop"]) as im:self.gray=im.convert("L")
        self.render()
        previous=self.store.state["answers"].get(sid,{})
        draft=self.store.state["drafts"].get(sid,previous)
        self.reason.set(draft.get("optional_reason") or "");self.observation.set(draft.get("observation") or "")
        self.current_answer.set("本项已有记录："+str(previous.get("status"))+"；类别="+str(previous.get("category"))+"（可返回修改）" if previous else "本项尚未处理；区域目标，无A/B成员" if not geometry else "本项尚未处理；目标身份由你判断")
        for b in self.answer_buttons:b.configure(state="normal")

    def render(self):
        row=self.rows[self.index]
        self.images=[ImageTk.PhotoImage(target_overlay(self.gray,row,self.display_scale,trial=True,members="none")),
                     ImageTk.PhotoImage(target_overlay(self.gray,row,self.display_scale,trial=True,members=self.mode))]
        self.left.configure(image=self.images[0]);self.right.configure(image=self.images[1])

    def choose(self,status,code=None):
        if self.index>=len(self.rows):return
        sid=self.rows[self.index]["sample_id"]
        try:self.store.answer(self.index,status,code,self.reason.get() or None,self.observation.get())
        except (OSError,ValueError) as error:self.failure(error);return
        self.saved.set("已保存 "+sid+"；"+str(self.store.path))
        self.show()

    def navigate(self,step):
        target=min(len(self.rows),max(0,self.index+step))
        try:self.store.navigate(target,self.observation.get(),self.reason.get() or None)
        except (OSError,ValueError) as error:self.failure(error);return
        self.saved.set("当前位置已保存；未新增类别。");self.show()

    def layer(self,mode):
        if self.index>=len(self.rows):return
        row=self.rows[self.index]
        if mode=="B" and len(row["candidate_geometry"])!=2:return
        if mode=="A" and not row["candidate_geometry"]:return
        try:self.store.view(row["sample_id"],layer=mode)
        except OSError as error:self.failure(error);return
        self.close_popups();self.mode=mode;self.render()

    def popup(self,title,image):
        top=tk.Toplevel(self.window);top.title(self.rows[self.index]["sample_id"]+" — "+title)
        canvas=tk.Canvas(top,width=min(image.width,1100),height=min(image.height,760))
        bar_y=ttk.Scrollbar(top,orient="vertical",command=canvas.yview);bar_x=ttk.Scrollbar(top,orient="horizontal",command=canvas.xview)
        canvas.configure(yscrollcommand=bar_y.set,xscrollcommand=bar_x.set,scrollregion=(0,0,image.width,image.height))
        bar_y.pack(side="right",fill="y");bar_x.pack(side="bottom",fill="x");canvas.pack(fill="both",expand=True)
        photo=ImageTk.PhotoImage(image);canvas.create_image(0,0,anchor="nw",image=photo);canvas.image=photo
        self.popups.append(top)

    def context(self):
        if self.index>=len(self.rows):return
        with Image.open(self.base/self.rows[self.index]["preview_files"]["context_raw"]) as im:self.popup("无叠加上下文；目标见主窗口",im.copy())

    def whole_page(self):
        if self.index>=len(self.rows):return
        row=self.rows[self.index]
        with Image.open(self.base/row["preview_files"]["page_position"]) as im:
            self.popup("当前"+row["sample_id"]+"裁块位置；红框不是计划观察区或其他目标",im.copy())

    def zoom(self,factor):
        if self.index>=len(self.rows):return
        row=self.rows[self.index]
        try:self.store.view(row["sample_id"],zoom_factor=factor,layer=self.mode)
        except OSError as error:self.failure(error);return
        image=Image.new("RGB",(1024,512),"white")
        image.paste(target_zoom(self.gray,row,factor),(0,0))
        image.paste(annotated_zoom(self.gray,row,factor,trial=True,members=self.mode),(512,0))
        self.popup(f"{factor}倍显示：原图／当前图层；局部视窗，完整端点见主图",image)

    def rules(self):messagebox.showinfo("本次分类规则与未覆盖范围",RULES,parent=self.window)

    def details(self):
        if self.index>=len(self.rows):return
        row=self.rows[self.index];geometry=row["candidate_geometry"]
        members="；".join("AB"[i]+"="+g[0] for i,g in enumerate(geometry)) if geometry else "区域目标，无A/B成员"
        messagebox.showinfo("提名信息，不是答案",f"{row['sample_id']}\n提名形式：{row['target_kind']}，不代表人工类别。\n{members}\n候选指向说明（待你核实）：{row['target_identity_description']}\n{row['geometry_fit_note']}\n{row['history_relation_status']}\n源路径：{row['source_path']}\n裁框xywh：{row['source_bbox']}\n容器族：{row['container_identity']['document_package_family']}\nprofile和STRUCTURAL GEOMETRY不是可靠对象归属或生产授权。",parent=self.window)

    def finish(self):
        try:self.store.finish(self.observation.get(),self.reason.get() or None)
        except OSError as error:self.failure(error);return
        counts=self.store.counts()
        messagebox.showinfo("已保存并结束",f"已处理 {counts['processed']}/{counts['total']}\n明确分类 {counts['classified']}\n暂缓 {counts['paused']}（含规则待定观察 {counts['rule_pending_observations']}）\n明确错误候选 {counts['invalid_candidates']}\n保存路径：{self.store.path}\n不训练、不审计、不冻结。",parent=self.window)
        self.close_popups();self.window.destroy()
