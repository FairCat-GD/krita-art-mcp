"""Build a proposed API catalogue and examples, not a running Krita server."""
from pathlib import Path
import json, copy
P=Path(__file__).resolve().parent
S={'type':'string','minLength':1}; N={'type':'number'}; I={'type':'integer'}; B={'type':'boolean'}
def enum(*v): return {'type':'string','enum':list(v)}
def obj(p, optional=()): return {'type':'object','properties':p,'required':[k for k in p if k not in optional],'additionalProperties':False}
def arr(item,minimum=0,maximum=None):
    d={'type':'array','items':item,'minItems':minimum}
    if maximum is not None:d['maxItems']=maximum
    return d
def tup(*items):return {'type':'array','prefixItems':list(items),'items':False,'minItems':len(items),'maxItems':len(items)}
def nullable(s):return {'anyOf':[s,{'type':'null'}]}
POS={'type':'integer','minimum':1}; NONNEG={'type':'integer','minimum':0}; UNIT={'type':'number','minimum':0,'maximum':1}
XY=tup(N,N); SIZE=tup(POS,POS); RECT=obj({'x':I,'y':I,'width':POS,'height':POS})
GUARD=obj({'document_id':S,'expected_revision':NONNEG,'request_id':S})
READ=obj({'document_id':S,'revision':NONNEG,'frame':NONNEG})
COLOR=obj({'space':enum('srgb'),'rgba':tup(UNIT,UNIT,UNIT,UNIT)})
HASH={'type':'string','pattern':'^[0-9a-f]{64}$'}
FILTER=enum('nearest','box','bilinear','bicubic','lanczos')
ARTIFACT=obj({'uri':S,'mime_type':S,'sha256':HASH,'size_bytes':NONNEG})
def infer(v):
    # Examples define the required receipt fields. Inputs use explicit types below.
    if v is None:return {'type':'null'}
    if isinstance(v,bool):return B
    if isinstance(v,int):return I
    if isinstance(v,float):return N
    if isinstance(v,str):return {'type':'string'}
    if isinstance(v,list):
        shapes=[]
        for x in v:
            shape=infer(x)
            if shape not in shapes:shapes.append(shape)
        return arr(shapes[0] if len(shapes)==1 else {'anyOf':shapes} if shapes else {})
    return obj({k:infer(x) for k,x in v.items()})
def artifact(name='preview.png'):return {'uri':'krita-artifact://example/'+name,'mime_type':'image/png' if name.endswith('.png') else 'application/json','sha256':'a'*64,'size_bytes':4096}
def guard(rev=12,req='req-001'):return dict(document_id='doc-1',expected_revision=rev,request_id=req)
def read(rev=12):return dict(document_id='doc-1',revision=rev,frame=0)
R=read(); G=guard(); rect={'x':16,'y':16,'width':32,'height':32}
tools=[]
def tool(name,phase,description,inputs,example,data,notes='',mutates=False,revision=12):
    output=obj({'api_version':{'const':'0.1.0'},'status':enum('completed','queued','running','failed','cancelled'),
        'document_id':nullable(S),'revision':nullable(NONNEG),'operation_id':nullable(S),
        'data':nullable(infer(data)), 'error':nullable(obj({'code':S,'message':S,'retryable':B,'details':{'type':'object'}}))})
    output['allOf']=[{'if':{'properties':{'status':{'const':'completed'}}},'then':{'properties':{'data':infer(data),'error':{'type':'null'}}}},
                    {'if':{'properties':{'status':{'const':'failed'}}},'then':{'properties':{'error':{'type':'object'}}}},
                    {'if':{'properties':{'status':{'enum':['queued','running']}}},'then':{'properties':{'operation_id':S,'data':{'type':'null'},'error':{'type':'null'}}}}]
    row={'name':'krita_'+name,'phase':phase,'description':description,'inputSchema':inputs,'outputSchema':output,
         'annotations':{'readOnlyHint':not mutates,'destructiveHint':mutates,'idempotentHint':True,'openWorldHint':False},
         'example':{'input':example,'structuredContent':{'api_version':'0.1.0','status':'completed','document_id':'doc-1' if revision is not None else None,'revision':revision,'operation_id':None,'data':data,'error':None}},'notes':notes}
    tools.append(row)

tool('server_info','MVP-A','Discover tested capabilities, limits and session identity.',obj({}),{},
 {'session_id':'session-1','krita_version':'detected-at-runtime','plugin_version':'0.1.0','profile_schema_version':'0.1.0',
  'capabilities':{'brush_strokes':True,'pressure':True,'tilt':False,'native_animation':False,'verified_rollback':True},
  'limits':{'stroke_points':4096,'capture_pixels':16777216,'edit_timeout_seconds':120},
  'unsupported':['native_animation','tilt']},'Example flags are fictional. Probe actual bindings and behavior; unsupported modules must not advertise successful tools.',revision=None)
tool('project_load','MVP-A','Validate and bind an immutable project profile.',obj({'profile_path':S,'expected_sha256':HASH,'request_id':S}),
 {'profile_path':'/projects/demo/art-profile.json','expected_sha256':'b'*64,'request_id':'req-profile'},
 {'project_id':'project-1','profile_sha256':'b'*64,'profile_version':1,'effective_profile_uri':'krita-artifact://example/profile.json','validator_ids':['alpha-bounds','source-geometry']},
 'Resolve profile paths under configured local roots. No network downloads or arbitrary validator commands. Existing documents keep their original profile binding.',True,None)
tool('document_list','MVP-A','List accessible documents without switching the active document.',obj({}),{},
 {'documents':[{'document_id':'doc-1','name':'hero-working.kra','revision':12,'dirty':True,'project_id':'project-1'}]},revision=None)
tool('document_open','MVP-A','Open a baseline and return an isolated working copy.',obj({'project_id':S,'source_path':S,'source_sha256':HASH,'mode':enum('working_copy','read_only'),'request_id':S}),
 {'project_id':'project-1','source_path':'/projects/demo/accepted/hero.kra','source_sha256':'c'*64,'mode':'working_copy','request_id':'req-open'},
 {'working_copy':True,'baseline_id':'baseline-1','source_sha256':'c'*64,'canvas_px':[128,128],'root_layer_id':'root-1'},
 'Opening cannot overwrite the source. Returned document ID/revision bind all later requests. Duplicate request IDs return the same handle.',True,1)
tool('document_create','MVP-A','Create new artwork with explicit canvas and colour settings.',obj({'project_id':S,'name':S,'size_px':SIZE,'color_model':enum('RGBA'),'depth':enum('U8','U16','F16','F32'),'profile_id':S,'background':enum('transparent'),'request_id':S}),
 {'project_id':'project-1','name':'new-icon','size_px':[32,32],'color_model':'RGBA','depth':'U8','profile_id':'srgb-profile-1','background':'transparent','request_id':'req-new'},
 {'canvas_px':[32,32],'root_layer_id':'root-2','initial_layer_id':'paint-1','profile_id':'srgb-profile-1'},'Reject unsupported colour depths/profile combinations. Do not inherit incidental foreground/background settings.',True,1)
tool('document_inspect','MVP-A','Read document state, frame, layer tree, profile and protection policy.',obj({'document_id':S}),{'document_id':'doc-1'},
 {'canvas_px':[128,128],'frame':0,'profile_id':'srgb-profile-1','project_id':'project-1','dirty':True,
  'layers':[{'id':'base-1','parent_id':'root-1','name':'Accepted base','type':'paint','visible':True,'opacity':1.0,'blend_mode':'normal','locked':True,'alpha_locked':False,'offset_px':[0,0]}],
  'protection_id':'protect-1','active_edit_id':None},'Layer IDs are session/document scoped; return remappings after reopen. Server identity must never depend on layer names.')
tool('document_close','MVP-C','Close a clean or explicitly checkpointed working document.',obj({'guard':GUARD,'dirty_policy':enum('refuse','discard_with_checkpoint'),'checkpoint_id':nullable(S)}),
 {'guard':G,'dirty_policy':'refuse','checkpoint_id':None},{'closed':True,'baseline_untouched':True},'Refuse dirty documents by default. Discard requires a verified recoverable checkpoint. No close during an active edit.',True,13)
tool('resource_list','MVP-A','Discover available brushes, profiles, palettes and blend modes.',obj({'kind':enum('brush','profile','palette','blend_mode'),'cursor':nullable(S),'limit':{'type':'integer','minimum':1,'maximum':100}}),
 {'kind':'brush','cursor':None,'limit':20},{'resources':[{'id':'brush-ink-1','name':'Ink','sha256':'d'*64,'supported_settings':['size_px','opacity','flow','color','pressure','eraser','smoothing','antialias']}],'next_cursor':None},
 'Enumerate actual resources and hashes, not guessed preset names. Capabilities may differ per preset.',revision=None)
tool('layer_create','MVP-B','Create an editable paint/group/mask node at an explicit stack position.',obj({'guard':GUARD,'parent_id':S,'above_id':nullable(S),'type':enum('paint','group','transparency_mask'),'name':S}),
 {'guard':G,'parent_id':'root-1','above_id':'base-1','type':'paint','name':'Accessory repair'},
 {'layer_id':'repair-1','parent_id':'root-1','above_id':'base-1','type':'paint'},'Masks attach only to compatible nodes. Protected parent topology may forbid insertion. Native undo and server revision must record this change.',True,13)
tool('layer_update','MVP-B','Set explicit layer properties without changing protected state.',obj({'guard':GUARD,'layer_id':S,'properties':obj({'name':S,'visible':B,'opacity':UNIT,'blend_mode':S,'locked':B,'alpha_locked':B,'inherit_alpha':B},optional=('name','visible','opacity','blend_mode','locked','alpha_locked','inherit_alpha'))}),
 {'guard':G,'layer_id':'repair-1','properties':{'alpha_locked':True}}, {'layer_id':'repair-1','effective_properties':{'alpha_locked':True}},
 'Require at least one property. Validate advertised blend modes. Layer locks are not permission to weaken server protection; protected layers cannot be unlocked by this tool.',True,13)
selection_shape={'oneOf':[obj({'type':{'const':'rect'},'rect':RECT}),obj({'type':{'const':'polygon'},'points':arr(XY,3,4096)}),obj({'type':{'const':'raster'},'mask_uri':S,'mask_sha256':HASH,'origin_px':tup(I,I)})]}
tool('selection_set','MVP-B','Create or combine an explicit document-space selection.',obj({'guard':GUARD,'combine':enum('replace','add','subtract','intersect'),'shape':selection_shape,'feather_px':{'type':'number','minimum':0},'invert':B}),
 {'guard':G,'combine':'replace','shape':{'type':'rect','rect':rect},'feather_px':0,'invert':False},
 {'selection_id':'selection-1','mask':artifact('selection.png'),'bounds_px':rect,'selected_pixels':1024},
 'Mask is full-canvas linear 8-bit coverage, not colour-managed luminance. Feathering changes selection weights, never expands the separately enforced hard allowed-change mask.',True,13)
tool('capture','MVP-A','Return a fresh lossless crop of a layer, composite or selection.',obj({'source':READ,'target':enum('composite','layer','selection'),'layer_id':nullable(S),'rect':RECT,'scale':{'type':'number','exclusiveMinimum':0},'filter':FILTER}),
 {'source':R,'target':'composite','layer_id':None,'rect':rect,'scale':1,'filter':'nearest'},
 {'image':artifact(),'output_size_px':[32,32],'source_rect':rect,'source_to_image':[1,0,-16,0,1,-16],'profile_id':'srgb-profile-1','fresh':True},
 'Require layer_id only for target=layer. Include native image content or readable resource; metadata alone is insufficient. Read revision mismatch returns STALE_REVISION, not a newer unlabelled capture.')
tool('sample','MVP-A','Sample known pixel locations with explicit layer/composite scope.',obj({'source':READ,'target':enum('composite','layer'),'layer_id':nullable(S),'points':arr(tup(I,I),1,256)}),
 {'source':R,'target':'composite','layer_id':None,'points':[[20,20]]},
 {'samples':[{'point_px':[20,20],'srgb_rgba':[0.5,0.3,0.2,1.0],'native_channels':[128,77,51,255]}],'native_profile_id':'srgb-profile-1','native_channel_order':'RGBA'},
 'Points address pixel cells; sample centers are (x+0.5,y+0.5). Expose actual native order/depth, never assume all Krita pixel buffers are RGBA.')
tool('checkpoint_create','MVP-B','Snapshot content, metadata and recoverable native state.',obj({'guard':GUARD,'label':S}),
 {'guard':G,'label':'Before accessory repair'}, {'checkpoint_id':'cp-1','content_sha256':'e'*64,'recoverable':True,'storage_uri':'krita-checkpoint://session-1/cp-1'},
 'Checkpoint creation does not change art/revision. Persist before claiming recoverable; report quota failure. Include layer tree, masks, frames, profile, selection and sidecars.',True,12)
tool('protection_set','MVP-B','Bind or tighten preservation policy against a checkpoint.',obj({'guard':GUARD,'checkpoint_id':S,'protected_layer_ids':arr(S,0,1024),'allowed_change_mask':nullable(obj({'uri':S,'sha256':HASH})),'preserve_composite_alpha':B,'preserve_canvas':B}),
 {'guard':G,'checkpoint_id':'cp-1','protected_layer_ids':['base-1'],'allowed_change_mask':{'uri':'krita-artifact://example/allowed.png','sha256':'f'*64},'preserve_composite_alpha':True,'preserve_canvas':True},
 {'protection_id':'protect-1','protected_layer_ids':['base-1'],'composite_outside_mask':'exact','preserve_composite_alpha':True},
 'Only initialize or tighten in MVP. Weakening requires a new explicitly authorized project policy/working copy. Protect appearance-affecting properties and ancestor operations as well as native pixels.',True,13)
tool('edit_begin','MVP-B','Begin one bounded, guarded paint transaction.',obj({'guard':GUARD,'protection_id':S,'target_layer_id':S,'frame':NONNEG,'selection_id':nullable(S),'label':S}),
 {'guard':G,'protection_id':'protect-1','target_layer_id':'repair-1','frame':0,'selection_id':'selection-1','label':'Repair one material edge'},
 {'edit_id':'edit-1','checkpoint_id':'cp-edit-1','target_layer_id':'repair-1','frame':0,'state':'open'},
 'One active edit per document. Capture rollback state before writing. Pin selection/brush context; never depend on the current UI layer. Only the allowed target/frame may change.',True,13)
BRUSH=obj({'preset_id':S,'preset_sha256':HASH,'size_px':{'type':'number','exclusiveMinimum':0},'opacity':UNIT,'flow':UNIT,'color':COLOR,'eraser':B,'smoothing':enum('none','basic','stabilizer'),'antialias':B})
POINT=obj({'x':N,'y':N,'pressure':UNIT,'time_ms':NONNEG,'tilt_x':{'type':'number','minimum':-90,'maximum':90},'tilt_y':{'type':'number','minimum':-90,'maximum':90}},optional=('tilt_x','tilt_y'))
tool('paint_stroke','MVP-B','Paint one native brush stroke on the transaction target.',obj({'guard':GUARD,'edit_id':S,'brush':BRUSH,'points':arr(POINT,1,4096)}),
 {'guard':G,'edit_id':'edit-1','brush':{'preset_id':'brush-ink-1','preset_sha256':'d'*64,'size_px':2,'opacity':1,'flow':1,'color':{'space':'srgb','rgba':[0.4,0.3,0.3,1]},'eraser':False,'smoothing':'none','antialias':True},'points':[{'x':22.5,'y':24.5,'pressure':0.4,'time_ms':0},{'x':27.5,'y':26.5,'pressure':0.7,'time_ms':30}]},
 {'stroke_id':'stroke-1','accepted_points':2,'changed_bounds_px':{'x':21,'y':23,'width':9,'height':5},'protected_pixels_changed':0,'preview':artifact('stroke.png')},
 'Require nondecreasing time. Unsupported settings fail preflight; never silently ignore tilt/flow/AA. Brush preset is immutable for the stroke. Repeated request_id cannot paint twice. Commit still checks the whole transaction.',True,13)
tool('edit_commit','MVP-B','Verify and commit a paint batch or roll it back on invariant failure.',obj({'guard':GUARD,'edit_id':S}),
 {'guard':G,'edit_id':'edit-1'}, {'committed':True,'checkpoint_id':'cp-edit-1','changed_pixels':27,'protected_pixels_changed':0,'alpha_changed_pixels':0,'diff':artifact('diff.png')},
 'Barrier for native paint/projection completion, then exact protected-content checks. No success until verified. A failed invariant is isError=true with rollback evidence, never a successful receipt.',True,13)
tool('edit_rollback','MVP-B','Restore the transaction baseline and verify the restoration.',obj({'guard':GUARD,'edit_id':S}),
 {'guard':G,'edit_id':'edit-1'}, {'rolled_back':True,'restored_checkpoint_id':'cp-edit-1','restored_content_sha256':'e'*64,'verified':True},
 'Restoring old content increments revision; revisions never go backwards. If a human edited concurrently, preserve both states and return EXTERNAL_EDIT_CONFLICT instead of erasing human work.',True,13)
tool('history_step','MVP-C','Undo or redo committed edits, or restore a named checkpoint.',obj({'guard':GUARD,'action':enum('undo','redo','restore_checkpoint'),'steps':POS,'checkpoint_id':nullable(S)}),
 {'guard':G,'action':'undo','steps':1,'checkpoint_id':None}, {'action':'undo','steps_applied':1,'verified':True,'content_sha256':'e'*64},
 'No active transaction. checkpoint_id is required only for restore_checkpoint, which requires steps=1. Restore art/history without weakening protection policy or decrementing revision.',True,13)
tool('operation_get','MVP-C','Read the status of a long-running operation.',obj({'operation_id':S}),{'operation_id':'op-export-1'},
 {'operation_id':'op-export-1','state':'completed','progress':1.0,'result_uri':'krita-artifact://example/export-receipt.json','rollback_state':'not_needed'},
 'The tool result completed means the status query completed; data.state is the operation state. Receipts are retained for a declared duration. Progress may be null/unknown in the implementation schema.')
tool('operation_cancel','MVP-C','Request cancellation and report verified final state.',obj({'operation_id':S,'request_id':S}),{'operation_id':'op-paint-1','request_id':'req-cancel'},
 {'operation_id':'op-paint-1','state':'cancelled','rollback_state':'verified','checkpoint_id':'cp-edit-1'},
 'If cancellation is pending, return queued/running instead of this completed example. Do not claim cancellation until writes stop and restoration is checked. Export cancellation deletes only its incomplete temporary output.',True)
tool('registration_set','MVP-C','Set export registration metadata without changing source pixels.',obj({'guard':GUARD,'asset_id':S,'source_rect':RECT,'uniform_scale':{'type':'number','exclusiveMinimum':0},'translation_px':XY,'output_size_px':SIZE,'anchor_px':XY,'filter':FILTER}),
 {'guard':G,'asset_id':'hero','source_rect':{'x':0,'y':0,'width':128,'height':128},'uniform_scale':0.5,'translation_px':[4,4],'output_size_px':[72,72],'anchor_px':[36,68],'filter':'lanczos'},
 {'registration_id':'reg-1','source_to_export':[0.5,0,4,0,0.5,4],'output_size_px':[72,72],'anchor_px':[36,68],'source_pixels_changed':0},
 'Mapping: export=(document-source_rect.origin)*scale+translation. Crop/clip and padding are explicit; reject inadvertent nontransparent clipping. Animation/frame references remain separately bound.',True,13)
tool('preview_render','MVP-C','Render a project-defined game-size or comparison/composition recipe.',obj({'project_id':S,'recipe_id':S,'sources':arr(obj({'asset_id':S,'source':READ,'registration_id':S}),1,256),'baseline_id':nullable(S),'overlays':arr(enum('anchor','collision','envelope','selection'),0,4)}),
 {'project_id':'project-1','recipe_id':'native-and-game-size','sources':[{'asset_id':'hero','source':R,'registration_id':'reg-1'}],'baseline_id':'baseline-1','overlays':['anchor']},
 {'images':[{'artifact':artifact('game-size.png'),'size_px':[36,36],'target_pixels_per_unit':2,'export_pixels_per_unit':4,'filter':'lanczos'}],'recipe_sha256':'b'*64,'static_only':True,'source_pixels_changed':0},
 'Recipe is validated project data, not code. Include actual per-axis mapping after rounding, fixed reference hashes, display-pixel assumptions and profile. Return unoverlaid render alongside overlays. UI recipes can use fixed pixel sizes instead of world units.')
tool('document_save','MVP-C','Save a new layered revision and verify it by reopening a copy.',obj({'guard':GUARD,'path':S,'overwrite':{'const':False},'verify_reopen':{'const':True}}),
 {'guard':G,'path':'/projects/demo/revisions/hero-r02.kra','overwrite':False,'verify_reopen':True},
 {'path':'/projects/demo/revisions/hero-r02.kra','sha256':'a'*64,'reopened_verified':True,'layers_preserved':True,'baseline_untouched':True},
 'Atomic write to a new path. Refuse active/uncommitted edits. Verification must include layer tree, masks, frames, profiles and pixels; reopening verification must not replace the live document.',True,12)
tool('asset_export','MVP-C','Export a registered transparent PNG and metadata from a pinned revision.',obj({'source':READ,'registration_id':S,'output_path':S,'profile_id':S,'alpha_mode':enum('straight','premultiplied'),'overwrite':{'const':False},'request_id':S}),
 {'source':R,'registration_id':'reg-1','output_path':'/projects/demo/exports/hero.png','profile_id':'srgb-profile-1','alpha_mode':'straight','overwrite':False,'request_id':'req-export'},
 {'path':'/projects/demo/exports/hero.png','sha256':'a'*64,'size_px':[72,72],'alpha_mode':'straight','metadata':artifact('hero.json'),'source_unchanged':True},
 'PNG MVP must support straight alpha; reject premultiplied requests until a tested project adapter explicitly supports and labels that convention. Never flatten the live source. Fail on profile mismatch/clipping; never auto-fix art.',True,12)
tool('validation_run','MVP-C','Run registered validators against immutable revision/export snapshots.',obj({'project_id':S,'validator_ids':arr(S,1,32),'artifact_uri':S,'artifact_sha256':HASH}),
 {'project_id':'project-1','validator_ids':['alpha-bounds','source-geometry'],'artifact_uri':'krita-artifact://example/hero.json','artifact_sha256':'a'*64},
 {'checks':[{'id':'alpha-bounds','status':'pass'},{'id':'source-geometry','status':'pass'}],'report':artifact('validation.json'),'art_approval':'unreviewed','runtime_validation':'not_run'},
 'Validation failure is data in checks, not a server execution failure. Execution errors use isError. Validators are separately registered local adapters, not arbitrary shell commands supplied by a tool caller.',revision=None)

# Extension catalogue: concrete examples plus intentionally provisional schemas.
# These are not part of the MVP implementation promise.
def extension(name,description,example,data,notes='',mutates=False):
    tool(name,'EXTENSION',description,infer(example),example,data,
         'Draft example shape; formal enum/range/union constraints must be finalized before exposure. '+notes,mutates)

extension('document_duplicate','Fork a working branch including project metadata.',{'guard':G,'name':'hero-option-b'}, {'new_document_id':'doc-2','new_revision':1,'baseline_id':'baseline-1','source_unchanged':True},mutates=True)
extension('layer_duplicate','Duplicate selected editable nodes and return ID mapping.',{'guard':G,'layer_ids':['repair-1'],'destination_parent_id':'root-1'}, {'id_map':{'repair-1':'repair-2'}},mutates=True)
extension('layer_reorder','Move editable nodes without changing their pixel data.',{'guard':G,'layer_id':'repair-1','parent_id':'root-1','above_id':'base-1'}, {'effective_order':['base-1','repair-1']},'Verify protected composite after reordering.',True)
extension('layer_remove','Remove editable nodes through a verified checkpoint.',{'guard':G,'layer_ids':['unused-1'],'checkpoint_id':'cp-1'}, {'removed':['unused-1'],'protected_nodes_unchanged':True},mutates=True)
extension('layer_import','Import local raster/vector content as a new explicitly positioned layer.',{'guard':G,'path':'/projects/demo/parts/hat.png','sha256':'a'*64,'origin_px':[0,0],'as_type':'paint'}, {'layer_id':'hat-1','source_size_px':[32,32],'rasterized':False},'Report any conversion; preserve SVG source when rasterization is authorized.',True)
extension('mask_edit','Create or edit a mask with explicit selection/brush semantics.',{'guard':G,'edit_id':'edit-1','mask_layer_id':'mask-1','operation':'fill_selection','coverage':128}, {'mask_layer_id':'mask-1','changed_pixels':120,'protected_pixels_changed':0},mutates=True)
extension('selection_query','Read a selection mask, bounds and coverage histogram.',{'source':R},{'selection_id':'selection-1','mask':artifact('selection.png'),'nonzero_pixels':1024})
extension('selection_clear','Clear or select the full canvas explicitly.',{'guard':G,'mode':'clear'}, {'selection_active':False},mutates=True)
extension('selection_from_alpha','Derive a selection from a known layer alpha.',{'guard':G,'layer_id':'repair-1','threshold':128,'combine':'replace'}, {'selection_id':'selection-alpha','selected_pixels':200},'Never confuse selection-generation with changing the painted contour.',True)
extension('paint_path','Paint a controlled Bezier path with the native brush.',{'guard':G,'edit_id':'edit-1','brush_id':'brush-ink-1','path':[{'command':'move','point':[10,10]},{'command':'cubic','control1':[15,10],'control2':[20,20],'point':[25,20]}]}, {'changed_pixels':37,'preview':artifact('path.png')},'Include full immutable brush settings in the finalized schema, as in paint_stroke.',True)
extension('paint_fill','Fill a bounded selection or contiguous region.',{'guard':G,'edit_id':'edit-1','mode':'selection','color':{'space':'srgb','rgba':[0.4,0.3,0.2,1]},'respect_alpha_lock':True}, {'filled_pixels':200,'outside_allowed_mask_changed':0},'Contiguous fill needs explicit tolerance, reference scope, expansion and feather parameters.',True)
extension('paint_clone','Clone from an explicit immutable source with bounded brush input.',{'guard':G,'edit_id':'edit-1','source':R,'source_layer_id':'base-1','source_offset_px':[-12,0],'points':[{'x':30.5,'y':20.5,'pressure':0.5,'time_ms':0}]}, {'changed_pixels':15,'source_unchanged':True},'Finalize brush settings and source snapshot behavior; no active-tool state dependence.',True)
extension('paint_shape','Draw a deliberate shape as paint or editable vector content.',{'guard':G,'edit_id':'edit-1','shape':'ellipse','rect':rect,'stroke_width_px':1,'fill':'none','output':'vector'}, {'layer_id':'shape-1','editable':True},'Explicit construction tool, never automatic replacement of an accepted silhouette.',True)
extension('transform_apply','Apply a requested transform to an editable target or transform mask.',{'guard':G,'layer_id':'repair-1','matrix':[1,0,2,0,1,0],'filter':'nearest','mode':'transform_mask'}, {'transform_mask_id':'transform-1','source_pixels_unchanged':True},'Handle rotation, mirror, perspective and warp as declared capabilities; disclose rasterization and clipping.',True)
extension('canvas_resize','Change working canvas bounds without silently scaling paint.',{'guard':G,'new_size_px':[160,160],'content_offset_px':[16,16],'clip_policy':'reject_nontransparent'}, {'size_px':[160,160],'anchor_delta_px':[16,16]},'Requires project policy permitting canvas changes; update offsets and sidecars together.',True)
extension('filter_apply','Apply an explicitly requested bounded adjustment or filter.',{'guard':G,'layer_id':'repair-1','filter_id':'gaussian-blur','parameters':{'radius_px':1},'mode':'filter_mask','selection_id':'selection-1'}, {'filter_mask_id':'filter-1','outside_allowed_mask_changed':0},'Discover supported parameter schemas. Exact preservation after projection, including filter halo. No automatic cleanup.',True)
extension('palette_manage','Read or create a versioned project palette.',{'project_id':'project-1','operation':'create','name':'eight-colour','colors':['#102030','#80A060'],'request_id':'req-palette'}, {'palette_id':'palette-2','sha256':'b'*64,'entries':2},'Changing a palette does not recolour existing pixels. Colour conversion is a separate explicit operation.',True)
extension('color_convert','Explicitly convert an authorized working copy to a target colour profile.',{'guard':G,'target_profile_id':'srgb-profile-1','intent':'relative_colorimetric','black_point_compensation':True,'checkpoint_id':'cp-1'}, {'converted':True,'profile_id':'srgb-profile-1','report':artifact('color-diff.json')},'Differentiate assign-profile from convert-profile; never silently substitute one.',True)
extension('diff_measure','Compare layer/native/composite snapshots and quantify differences.',{'before_checkpoint_id':'cp-1','after':R,'scope':'composite','metric':'exact_rgba','region':rect}, {'changed_pixels':27,'alpha_changed_pixels':0,'diff':artifact('diff.png'),'bounds_px':rect},'Also support palette occupancy, alpha topology, bounds and optional colour metrics with explicit units.')
extension('reference_set','Register approved references and board crops without painting them into art.',{'project_id':'project-1','references':[{'path':'/projects/demo/board.png','sha256':'a'*64,'role':'approved-board','crop_px':[0,0,512,512]}],'request_id':'req-ref'}, {'reference_set_id':'refs-1','count':1},mutates=True)
extension('guides_set','Set document guides, grid and snapping as explicit working state.',{'guard':G,'grid_px':[8,8],'origin_px':[0,0],'snap':True,'horizontal':[32],'vertical':[32]}, {'grid_px':[8,8],'snap':True},mutates=True)
extension('view_set','Set UI zoom/pan/rotation without changing document-coordinate semantics.',{'document_id':'doc-1','zoom':4,'pan_px':[0,0],'rotation_degrees':0,'request_id':'req-view'}, {'zoom':4,'document_pixels_per_device_pixel':0.25,'art_changed':False},'Report actual display scale; UI viewport state has its own revision and must not masquerade as document paint.',True)
extension('asset_metadata_set','Edit typed pivots, sockets, collision or nine-slice metadata separately.',{'guard':G,'asset_id':'hero','schema_id':'sprite-metadata-v1','metadata':{'pivot_px':[64,120],'sockets':{'hand':[82,64]},'collision':{'type':'polygon','vertices':[[40,40],[80,40],[80,100],[40,100]]}}}, {'metadata_id':'meta-1','source_pixels_changed':0,'validation_status':'pass'},'No automatic enlargement of limits; project adapters own semantic rules.',True)
extension('animation_inspect','Read layers, clips, keyframes, holds and timing.',{'source':R}, {'fps':12,'clips':[{'id':'idle','start':0,'end_exclusive':4}],'keyframes':[{'layer_id':'body-1','frame':0,'hold_frames':2}]})
extension('animation_frame_edit','Insert, duplicate, move or delete explicit keyframes.',{'guard':G,'layer_id':'body-1','operation':'duplicate','from_frame':0,'to_frame':2}, {'layer_id':'body-1','created_frame':2,'other_frames_unchanged':True},'Mutations must be frame-specific and protect unrequested frames. Final schema discriminates operations.',True)
extension('animation_clip_set','Define clips and timing without changing frame pixels.',{'guard':G,'clip_id':'idle','start':0,'end_exclusive':4,'fps':12,'loop':True}, {'clip_id':'idle','duration_seconds':0.3333333333,'pixels_changed':0},mutates=True)
extension('animation_preview','Render onion skins, contact sheets or timed playback.',{'source':R,'clip_id':'idle','mode':'contact_sheet','scale':2,'filter':'nearest','show_pivot':True}, {'sheet':artifact('idle-sheet.png'),'frames':4,'durations_ms':[83.333333,83.333333,83.333333,83.333333],'runtime_verified':False},'Playback mode returns timed media with exact rational timing metadata and reports dropped preview frames.')
extension('animation_export','Export ordered frame images and clip metadata.',{'source':R,'clip_id':'idle','registration_id':'reg-1','destination':'/projects/demo/exports/idle','request_id':'req-anim'}, {'frames_exported':4,'metadata':artifact('idle.json'),'pivot_stable':True},'Declare crop policy and offsets; retain frame rate/holds and optional project root motion.',True)
extension('tile_configure','Bind repeat axes, tile size, adjacency and wrap painting behavior.',{'guard':G,'tile_size_px':[32,32],'repeat_axes':['x','y'],'wrap_paint':True}, {'tile_id':'tile-1','wrap_paint':True},'Check native wrap support. Never fake wrapped paint with only a repeated preview.',True)
extension('tile_preview','Render repeated patches and measure shared seams/corners.',{'source':R,'repeat':[3,3],'filter':'nearest','seam_policy':'matching-edge-pixels'}, {'image':artifact('tile-patch.png'),'edge_mismatches':0,'corner_mismatches':0},'Seam policy is project-specific; exact opposite-edge equality is not a universal definition of seamless art.')
extension('tileset_export','Export a declared tile/adjoining-variant layout.',{'project_id':'project-1','layout_id':'terrain-16','source_ids':['tile-1','tile-2'],'destination':'/projects/demo/exports/terrain','request_id':'req-tiles'}, {'tile_count':2,'layout':artifact('terrain.json'),'missing_slots':['slot-3']},'Report missing variants; never invent art to fill slots.',True)
extension('scene_render','Compose immutable assets with explicit transforms and draw order.',{'project_id':'project-1','scene_id':'level-proof','viewport_px':[640,360],'camera_px':[0,0],'lighting_id':'noon','asset_revisions':{'hero':12}}, {'image':artifact('scene.png'),'viewport_px':[640,360],'missing_assets':[],'static_only':True},'Scene manifests pin source revision/hash, registration, clip frame, anchor, z/order and profile.')
extension('background_preview','Preview parallax/repeat layers at camera positions.',{'project_id':'project-1','scene_id':'parallax-proof','camera_positions_px':[[0,0],[320,0]],'viewport_px':[640,360]}, {'frames':[artifact('camera-0.png'),artifact('camera-1.png')],'seam_report':artifact('background-seams.json')},'Offscreen preview is evidence of composition, not engine/device performance.')
extension('ui_preview','Render UI assets at native sizes, states and nine-slice stretches.',{'project_id':'project-1','layout_id':'hud-proof','display_scale':1,'panel_sizes_px':[[160,48],[240,64]],'state_ids':['normal','pressed']}, {'image':artifact('hud.png'),'nine_slice_checks':'pass','native_pixel_sizes_preserved':True})
extension('text_edit','Create or update editable text when supported.',{'guard':G,'layer_id':'text-1','text':'PLAY','font_resource_id':'font-1','size_px':16,'bounds_px':rect}, {'editable':True,'missing_glyphs':[],'font_substitution':False},'Reject unknown fonts rather than substituting. Report shaping and rasterization limits; never claim editable text after flattening.',True)
extension('vector_edit','Edit declared vector shapes without silently rasterizing them.',{'guard':G,'layer_id':'shape-1','operation':'set_path','svg_path':'M 0 0 L 16 0 L 8 16 Z','fill':'#80A060'}, {'editable':True,'rasterized':False},'Parse bounded SVG input; reject external resource links and unsupported constructs.',True)
extension('atlas_pack','Pack existing exports with explicit trim, padding and rotation rules.',{'project_id':'project-1','asset_manifest_uri':'krita-artifact://example/assets.json','max_size_px':[1024,1024],'padding_px':2,'extrude_px':1,'trim':True,'allow_rotation':False,'destination':'/projects/demo/exports/atlas','request_id':'req-atlas'}, {'pages':1,'metadata':artifact('atlas.json'),'pivot_roundtrip_verified':True},'Preserve trim offsets, source hashes and anchors. Packing cannot repaint source assets.',True)
extension('export_batch','Export an explicit bounded set using per-asset registrations.',{'project_id':'project-1','items':[{'asset_id':'hero','source':R,'registration_id':'reg-1'}],'destination':'/projects/demo/exports/batch','request_id':'req-batch'}, {'succeeded':['hero'],'failed':[],'manifest':artifact('batch.json')},'Explicit per-item results. Do not claim cross-document atomicity unless implemented; temporary outputs must not look like committed delivery.',True)
extension('engine_package','Build an engine-specific handoff through a registered adapter.',{'project_id':'project-1','adapter_id':'engine-json-v1','manifest_uri':'krita-artifact://example/batch.json','destination':'/projects/demo/handoff','request_id':'req-package'}, {'package_uri':'krita-artifact://example/package.zip','manifest':artifact('handoff.json'),'runtime_import_test':'not_run'},'No game deployment or automatic import into a live project; capability-test each adapter separately.',True)
extension('recovery_list','List recoverable checkpoints and interrupted edit branches.',{'project_id':'project-1'}, {'recoveries':[{'id':'recovery-1','document_name':'hero-working','last_verified_revision':12,'state':'interrupted'}]})
extension('recovery_open','Open a recoverable state as a separate working document.',{'recovery_id':'recovery-1','request_id':'req-recover'}, {'document_id':'doc-recovered','revision':1,'verified':True,'original_untouched':True},mutates=True)
extension('diagnostics_get','Retrieve bounded plugin errors and capability probe reports.',{'operation_id':'op-export-1','max_events':20}, {'events':[{'severity':'info','message':'Export completed'}],'probe_report_uri':'krita-artifact://example/probes.json'},'Redact credentials and unrelated document paths; report API fallback and latency, not full image buffers.')

PROFILE_SCHEMA=obj({'schema_version':{'const':'0.1.0'},'project_id':S,'version':POS,'working_roots':arr(S,1),
 'art_mode':enum('painted','high_resolution_ui','mixed_raster'),'color_profile_id':S,'export_pixels_per_unit':nullable({'type':'number','exclusiveMinimum':0}),
 'palette_id':nullable(S),'filter':FILTER,'review_recipes':arr(obj({'id':S,'target_pixels_per_unit':nullable({'type':'number','exclusiveMinimum':0}),'target_size_px':nullable(SIZE),'integer_zoom':nullable(POS)}),1),
 'defaults':obj({'preserve_accepted_sources':B,'automatic_palette_conversion':{'const':False},'automatic_contour_replacement':{'const':False}}),
 'validator_ids':arr(S),'approval_policy_id':S})
profiles=[{'schema_version':'0.1.0','project_id':'painted-demo','version':1,'working_roots':['/projects/demo'],'art_mode':'painted','color_profile_id':'srgb-profile-1','export_pixels_per_unit':4,'palette_id':None,'filter':'lanczos','review_recipes':[{'id':'game-size','target_pixels_per_unit':1.8,'target_size_px':None,'integer_zoom':None},{'id':'native-and-game-size','target_pixels_per_unit':2,'target_size_px':None,'integer_zoom':None}],'defaults':{'preserve_accepted_sources':True,'automatic_palette_conversion':False,'automatic_contour_replacement':False},'validator_ids':['alpha-bounds','source-geometry'],'approval_policy_id':'first-variant-review'},
 {'schema_version':'0.1.0','project_id':'ui-demo','version':1,'working_roots':['/projects/ui-demo'],'art_mode':'high_resolution_ui','color_profile_id':'srgb-profile-1','export_pixels_per_unit':None,'palette_id':None,'filter':'lanczos','review_recipes':[{'id':'painted-icon-128','target_pixels_per_unit':None,'target_size_px':[128,128],'integer_zoom':1},{'id':'painted-icon-256','target_pixels_per_unit':None,'target_size_px':[256,256],'integer_zoom':1}],'defaults':{'preserve_accepted_sources':True,'automatic_palette_conversion':False,'automatic_contour_replacement':False},'validator_ids':['alpha-bounds','ui-safe-area'],'approval_policy_id':'project-owner-review'}]

# Success schemas describe variable receipts, not only one captured example.
def result_fields(name,patch,example_patch=None):
    t=next(t for t in tools if t['name']=='krita_'+name)
    for schema in [t['outputSchema']['properties']['data']['anyOf'][0],t['outputSchema']['allOf'][0]['then']['properties']['data']]:
        schema['properties'].update(patch)
        for key in patch:
            if key not in schema['required']:schema['required'].append(key)
    if example_patch:t['example']['structuredContent']['data'].update(example_patch)
result_fields('document_inspect',{'active_edit_id':nullable(S)})
result_fields('resource_list',{'next_cursor':nullable(S)})
result_fields('operation_get',{'state':enum('queued','running','completed','failed','cancelled'), 'progress':nullable(UNIT), 'result_uri':nullable(S),'rollback_state':enum('not_needed','pending','verified','failed','conflict')})
result_fields('operation_cancel',{'state':enum('cancelled','completed'),'rollback_state':enum('not_needed','verified')})
stroke=next(t for t in tools if t['name']=='krita_paint_stroke')
result_fields('paint_stroke',{'effective_brush':BRUSH},{'effective_brush':copy.deepcopy(stroke['example']['input']['brush'])})
preview=next(t for t in tools if t['name']=='krita_preview_render')
for schema in [preview['outputSchema']['properties']['data']['anyOf'][0],preview['outputSchema']['allOf'][0]['then']['properties']['data']]:
    props=schema['properties']['images']['items']['properties']
    props['target_pixels_per_unit']=nullable({'type':'number','exclusiveMinimum':0})
    props['export_pixels_per_unit']=nullable({'type':'number','exclusiveMinimum':0})
result_fields('preview_render',{'clean_images':arr(ARTIFACT,1)}, {'clean_images':[artifact('game-size-clean.png')]})
layer_update=next(t for t in tools if t['name']=='krita_layer_update')
layer_update['inputSchema']['properties']['properties']['minProperties']=1
# Receipts echo the actual set of updated properties, rather than one example key.
result_fields('layer_update',{'effective_properties':layer_update['inputSchema']['properties']['properties']})
for name in ['capture','sample']:
    t=next(t for t in tools if t['name']=='krita_'+name)
    t['inputSchema']['allOf']=[{'if':{'properties':{'target':{'const':'layer'}}},'then':{'properties':{'layer_id':S}},'else':{'properties':{'layer_id':{'type':'null'}}}}]
history=next(t for t in tools if t['name']=='krita_history_step')
history['inputSchema']['allOf']=[{'if':{'properties':{'action':{'const':'restore_checkpoint'}}},'then':{'properties':{'checkpoint_id':S,'steps':{'const':1}}},'else':{'properties':{'checkpoint_id':{'type':'null'}}}}]

def write(name,data): (P/name).write_text(json.dumps(data,indent=2)+'\n')
write('tools.json',{'api_version':'0.1.0','status':'proposed-unimplemented','tools':tools})
write('mvp.tools.json',{'tools':[{k:t[k] for k in ['name','description','inputSchema','outputSchema','annotations']} for t in tools if t['phase'].startswith('MVP')]})
write('profile.schema.json',{'$schema':'https://json-schema.org/draft/2020-12/schema',**PROFILE_SCHEMA})
for profile in profiles:write(profile['project_id']+'.profile.json',profile)

# Full request/result conversation with monotonically changing revision numbers.
sequence=[]
for name,rev_in,rev_out in [('document_inspect',12,12),('checkpoint_create',12,12),('layer_create',12,13),('selection_set',13,14),('protection_set',14,15),('edit_begin',15,16),('paint_stroke',16,17),('capture',17,17),('edit_commit',17,18),('registration_set',18,19),('preview_render',19,19),('document_save',19,19),('asset_export',19,19),('validation_run',None,None)]:
    t=next(t for t in tools if t['name']=='krita_'+name);e=copy.deepcopy(t['example']);args=e['input']
    if 'guard' in args:args['guard']=guard(rev_in,'workflow-'+name)
    if 'source' in args:args['source']=read(rev_in)
    if 'sources' in args:
        for src in args['sources']:src['source']=read(rev_in)
    if name=='protection_set':args['allowed_change_mask']={'uri':'krita-artifact://example/selection.png','sha256':'a'*64}
    out=e['structuredContent'];out['revision']=rev_out
    if name=='capture':args['target']='layer';args['layer_id']='repair-1'
    sequence.append({'call':{'name':t['name'],'arguments':args},'result':{'content':[{'type':'text','text':name+' completed'}],'structuredContent':out,'isError':False}})
write('paint-workflow.example.json',sequence)
errors=[]
for code,msg,retryable,details in [('STALE_REVISION','Expected revision 16; current revision is 17.',False,{'expected':16,'actual':17,'writes_performed':False}),('PROTECTED_REGION_CHANGED','Commit rejected; changes escaped the allowed mask.',False,{'changed_pixels_outside':2,'rolled_back':True,'rollback_verified':True,'checkpoint_id':'cp-edit-1'}),('UNSUPPORTED_CAPABILITY','This brush backend does not support requested tilt.',False,{'setting':'tilt','writes_performed':False}),('REQUEST_ID_CONFLICT','Request ID already used with different arguments.',False,{'writes_performed':False}),('EXTERNAL_EDIT_CONFLICT','Human edit detected during transaction; recoverable branches retained.',False,{'rollback_verified':False,'recovery_id':'recovery-1'}),('BUSY','Document has another active operation.',True,{'retry_after_ms':500,'writes_performed':False})]:
    errors.append({'content':[{'type':'text','text':msg}],'structuredContent':{'api_version':'0.1.0','status':'failed','document_id':'doc-1','revision':17,'operation_id':None,'data':None,'error':{'code':code,'message':msg,'retryable':retryable,'details':details}},'isError':True})
write('errors.example.json',errors)

lines=['# Krita MCP proposed tool catalogue','',
       'API proposal 0.1.0. These tools and receipts are examples, not implemented or observed Krita behavior. Fictional IDs, hashes, paths and resource URIs must be replaced by real values. See [the contract](README.md) for semantics and build order.','',
       'Inputs below are complete per-tool examples. Outputs show the `data` field of the common result envelope; complete examples and schemas are in [tools.json](tools.json). Extension schemas are draft example shapes, not final implementation contracts.','']
for t in tools:
    lines += ['**'+t['name']+' · '+t['phase']+'**','',t['description'],'','Input:','```json',json.dumps(t['example']['input'],indent=2),'```','','Output data:','```json',json.dumps(t['example']['structuredContent']['data'],indent=2),'```','',t['notes'],'']
(P/'TOOL-CATALOGUE.md').write_text('\n'.join(lines))
print('Built',len(tools),'tools;',sum(t['phase'].startswith('MVP') for t in tools),'MVP and',sum(t['phase']=='EXTENSION' for t in tools),'extensions.')
