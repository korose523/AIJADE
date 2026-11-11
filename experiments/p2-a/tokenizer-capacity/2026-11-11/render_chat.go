// Render the single-user, optional-default-system requests used by this study.
// The installed models' exact Go templates are inputs, not reimplemented strings.
package main

import (
    "bufio"
    "encoding/json"
    "fmt"
    "os"
    "text/template"
    "bytes"
)

type Message struct { Role string; Content string }
type Request struct { ID string `json:"id"`; Content string `json:"content"` }
type Response struct { ID string `json:"id"`; Prompt string `json:"prompt"` }

func main() {
    if len(os.Args)!=3 { panic("usage: render_chat TEMPLATE_FILE SYSTEM_FILE") }
    raw,err:=os.ReadFile(os.Args[1]);if err!=nil {panic(err)}
    system,err:=os.ReadFile(os.Args[2]);if err!=nil {panic(err)}
    compiled,err:=template.New("model").Parse(string(raw));if err!=nil {panic(err)}
    scanner:=bufio.NewScanner(os.Stdin);scanner.Buffer(make([]byte,65536),4*1024*1024)
    writer:=json.NewEncoder(os.Stdout)
    for scanner.Scan() {
        var input Request
        if err:=json.Unmarshal(scanner.Bytes(),&input);err!=nil {panic(err)}
        messages:=[]Message{}
        if len(system)>0 {messages=append(messages,Message{"system",string(system)})}
        messages=append(messages,Message{"user",input.Content})
        values:=map[string]any{"System":string(system),"Messages":messages,"Tools":[]any{},"Response":"","Prompt":"","Suffix":"","Think":false,"ThinkLevel":"","IsThinkSet":false}
        var output bytes.Buffer
        if err:=compiled.Execute(&output,values);err!=nil {panic(err)}
        if err:=writer.Encode(Response{input.ID,output.String()});err!=nil {panic(err)}
    }
    if err:=scanner.Err();err!=nil {fmt.Fprintln(os.Stderr,err);os.Exit(2)}
}
