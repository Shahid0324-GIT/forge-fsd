// Static framework diagnostics only. Never execute application modules or rewrite source.
export function diagnoseModule(ts,path,text){
  const source=ts.createSourceFile(path,text,ts.ScriptTarget.Latest,true);
  const findings=[];
  const add=(node,code,message)=>{
    const position=source.getLineAndCharacterOfPosition(node.getStart(source));
    findings.push({file:path,line:position.line+1,column:position.character+1,code,message});
  };
  const first=source.statements[0];
  let client=false;
  for(const statement of source.statements){
    if(!ts.isExpressionStatement(statement)||!ts.isStringLiteral(statement.expression))break;
    if(statement.expression.text==='use client')client=true;
  }
  const scanner=ts.createScanner(ts.ScriptTarget.Latest,true,ts.LanguageVariant.Standard,text);
  scanner.scan();const start=scanner.getTokenText();scanner.scan();const next=scanner.getTokenText();
  if(start==='use'&&['client','server'].includes(next)&&first)
    add(first,'INVALID_MODULE_DIRECTIVE',`The first statement is unquoted. Replace it with the string-literal statement '${start} ${next}'; including both quotes. Do not remove a client boundary needed by hooks.`);
  for(const statement of source.statements){
    if(ts.isImportDeclaration(statement)&&statement.moduleSpecifier.text==='react'){
      const bindings=statement.importClause?.namedBindings;
      if(bindings&&ts.isNamedImports(bindings)&&bindings.elements.some(element=>
        ['useState','useEffect','useReducer','useRef','useLayoutEffect','useContext'].includes((element.propertyName??element.name).text))&&!client)
        add(statement,'CLIENT_HOOK_WITHOUT_DIRECTIVE',"This module imports a client hook but has no quoted 'use client' directive. Keep the hook behavior and declare the client boundary before imports, or move interactive code to a client component.");
    }
    if(client&&statement.modifiers?.some(modifier=>modifier.kind===ts.SyntaxKind.ExportKeyword)){
      const names=ts.isVariableStatement(statement)?statement.declarationList.declarations.map(declaration=>declaration.name.getText(source)):
        ts.isFunctionDeclaration(statement)?[statement.name?.text]:[];
      if(names.some(name=>['metadata','generateMetadata'].includes(name)))
        add(statement,'CLIENT_SERVER_METADATA',"A client module exports server metadata. Preserve the metadata in a server page/layout and interactive behavior in a client module; do not delete the requested metadata.");
    }
  }
  return findings;
}
