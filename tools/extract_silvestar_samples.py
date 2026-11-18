import bpy, sys, json, numpy as np, time
from mathutils import Matrix
argv=sys.argv[sys.argv.index("--")+1:]
out=argv[0]; jobs=json.loads(argv[1])
scn=bpy.context.scene
def unhide(o):
    o.hide_viewport=False; o.hide_set(False) if o.name in bpy.context.view_layer.objects else None
def run(job):
    arm=bpy.data.objects[job["arm"]]
    unhide(arm)
    if arm.parent: unhide(arm.parent)
    ad=arm.animation_data
    for tn in job.get("mute",[]):
        for t in ad.nla_tracks:
            if t.name==tn: t.mute=True; print("muted",tn)
    for bn,cn in job.get("zero_cons",[]):
        arm.pose.bones[bn].constraints[cn].influence=0.0
    pbs=list(arm.pose.bones)
    names=[p.name for p in pbs]
    ext=[]
    for p in pbs:
        for k in p.constraints:
            t=getattr(k,"target",None)
            if t is not None and t!=arm and p.name not in ext: ext.append(p.name)
            st=getattr(k,"subtarget","") or ""
            if t==arm and st.startswith(("BASE_","EDIT_")) and p.name not in ext:
                ext.append(p.name); print("INTCON",p.name,k.type,k.name,st,k.influence,k.mute,getattr(k,"mix_mode",""),getattr(k,"owner_space",""),getattr(k,"target_space",""))
    ref=bpy.data.objects.get("ARM_Silvestar_01")
    if ref and ref!=arm:
        for p in pbs:
            if p.name in ref.pose.bones:
                d=(ref.data.bones[p.name].matrix_local.translation-arm.data.bones[p.name].matrix_local.translation).length
                if d>1e-5: print("RESTDIFF",p.name,round(d*1000,2))
                ca=[(k.type,getattr(k,"subtarget","")) for k in ref.pose.bones[p.name].constraints]; cb=[(k.type,getattr(k,"subtarget","")) for k in p.constraints]
                if ca!=cb and not p.name.startswith(("ORG","DEF")): print("CONDIFF",p.name,ca,cb)
        extra=[p.name for p in pbs if p.name not in ref.pose.bones]; print("EXTRA_BONES",extra)
        for n in extra:
            p=arm.pose.bones[n]; print("  ",n,"parent",p.parent.name if p.parent else None,[(k.type,getattr(k,'subtarget','')) for k in p.constraints],"children",[c.name for c in p.children])
    props=[]
    for p in pbs:
        for k in p.keys():
            v=p[k]
            if isinstance(v,(int,float)) and not k.startswith("_"): props.append((p.name,k))
    defi=[i for i,n in enumerate(names) if n.startswith("DEF-")]
    f0,f1=job["frames"]; F=f1-f0+1
    basis=np.zeros((F,len(pbs),16),np.float32); pv=np.zeros((F,len(props)),np.float32)
    armw=np.zeros((F,16),np.float64); defm=np.zeros((F,len(defi),16),np.float32)
    ctli=[i for i,n in enumerate(names) if not n.startswith(("ORG-","MCH-","DEF-","VIS_","BASE_","EDIT_"))] if job.get("pose") else []
    posem=np.zeros((F,len(ctli),16),np.float32)
    t0=time.time()
    for fi,f in enumerate(range(f0,f1+1)):
        scn.frame_set(f)
        dg=bpy.context.evaluated_depsgraph_get()
        ae=arm.evaluated_get(dg)
        armw[fi]=np.array(ae.matrix_world).ravel()
        for i,p in enumerate(ae.pose.bones):
            if p.name in ext:
                m=ae.convert_space(pose_bone=p,matrix=p.matrix,from_space='POSE',to_space='LOCAL')
            else: m=p.matrix_basis
            basis[fi,i]=np.array(m).ravel()
        for j,(bn,k) in enumerate(props): pv[fi,j]=float(ae.pose.bones[bn][k])
        for j,i in enumerate(defi): defm[fi,j]=np.array(ae.pose.bones[i].matrix).ravel()
        for j,i in enumerate(ctli): posem[fi,j]=np.array(ae.pose.bones[i].matrix).ravel()
        if fi%50==0: print(job["key"],f,round(time.time()-t0,1),flush=True)
    np.savez_compressed(out+"_"+job["key"]+".npz",basis=basis,props=pv,posem=posem,posenames=np.array([names[i] for i in ctli]),armw=armw,defm=defm,
        names=np.array(names),ext=np.array(ext),propnames=np.array(["%s|%s"%p for p in props]),
        defnames=np.array([names[i] for i in defi]),modes=np.array([p.rotation_mode for p in pbs]),f0=f0)
    print("saved",job["key"],ext)
for j in jobs: run(j)
