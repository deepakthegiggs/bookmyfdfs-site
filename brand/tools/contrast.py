"""WCAG contrast for every FDFS text pair, both themes. Exit 1 if any < 4.5."""
import sys
def L(h):
    h=h.lstrip('#'); c=[int(h[i:i+2],16)/255 for i in (0,2,4)]
    c=[x/12.92 if x<=.03928 else ((x+.055)/1.055)**2.4 for x in c]
    return .2126*c[0]+.7152*c[1]+.0722*c[2]
def cr(a,b):
    a,b=L(a),L(b); return (max(a,b)+.05)/(min(a,b)+.05)
def over(fg,a,bg):  # alpha-composite an rgba tint over a solid
    f=[int(fg[i:i+2],16) for i in (1,3,5)]; g=[int(bg[i:i+2],16) for i in (1,3,5)]
    return '#'+''.join('%02x'%round(a*x+(1-a)*y) for x,y in zip(f,g))
light=dict(bg='#FBF6EC',surface='#FFFCF6',s2='#F3EBDC')
dark=dict(bg='#0E0C1D',surface='#17142B',s2='#211D3B')
pairs=[('light','text #17142B','#17142B',['bg','surface','s2']),
('light','text-2 #4E4864','#4E4864',['bg','surface','s2']),
('light','text-3 #625C76','#625C76',['bg','surface','s2']),
('light','accent-text #8A4B00','#8A4B00',['bg','surface','s2']),
('light','ok #1D6B45 on ok-bg','#1D6B45',[('#E2F1E7',)]),
('light','note #8B2F4E on note-bg','#8B2F4E',[('#F7E4EA',)]),
('light','ink on marigold','#17142B',[('#F2A12E',)]),
('hall','hall-text','#F5EFE3',[('#0E0C1D',)]),('hall','hall-text-2','#C9C1D8',[('#0E0C1D',)]),
('hall','marigold-300 on hall','#F7C46E',[('#0E0C1D',)]),
('dark','text','#F5EFE3',['bg','surface','s2']),('dark','text-2','#C9C1D8',['bg','surface','s2']),
('dark','text-3 #A79FBA','#A79FBA',['bg','surface','s2']),
('dark','accent-text #F7C46E','#F7C46E',['bg','surface','s2']),
('dark','ok #7FD6A6 on ok tint','#7FD6A6',[(over('#7FD6A6',.12,'#17142B'),)]),
('dark','note #F0A3BD on tint','#F0A3BD',[(over('#F0A3BD',.12,'#17142B'),)]),
('dark','night on marigold-400','#0E0C1D',[('#F5AC3D',)])]
bad=0
for theme,name,fg,bgs in pairs:
    for b in bgs:
        col=b[0] if isinstance(b,tuple) else (light if theme=='light' else dark)[b]
        r=cr(fg,col); bad+=r<4.5
        print(f"{theme:5} {name:28} on {col}: {r:5.2f} {'OK' if r>=4.5 else 'FAIL'}")
sys.exit(1 if bad else 0)
